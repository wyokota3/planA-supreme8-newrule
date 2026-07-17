# -*- coding: utf-8 -*-
"""F-020: T2 の本来型 NeuPSL(supreme3 の中核・ADR 0052-supreme3)。

supreme2 の T2(role / relation / mode)を、本来の NeuPSL の4要素で置き換える:
  ① ニューラル述語 — 生特徴から軟真理値 [0,1] を出す微小 MLP(決定的初期化・学習可)
  ② 重み付き論理ルール — Łukasiewicz 緩和の含意規則(重み学習可・非負)
  ③ 結合 MAP 推論 — シナリオ内の全フレーム×3層を HL-MRF として同時最適化
     (射影劣勾配降下+層ごとの単体射影。時間持続ルールにより真の集合推論)
  ④ 学習 — 構造化パーセプトロン(GT 割当と MAP 解のエネルギー差の劣勾配)で
     ルール重みと MLP パラメータを同時更新

規律: stdlib のみ・乱数/時刻なし(初期化は決定的な擬似乱数列)・学習は train のみ。
supreme2 のヒステリシスは「持続ルール Mode(f-1,m) → Mode(f,m)」として PSL 内に宣言する。
"""
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 語彙(v1.4)
# ---------------------------------------------------------------------------
MODES = ["conv_request", "conv_ongoing", "surround_activity", "forward_caution",
         "side_rear_caution", "alert_required", "emergency", "quiet_standby", "env_change",
         "uncertain"]
ROLES = ["source_speech", "source_vehicle", "source_alarm", "source_human",
         "source_object", "unknown"]
RELS = ["addressing_user", "near_user", "approaching", "grouped", "departing", "unrelated"]
LAYERS = (("mode", MODES), ("role", ROLES), ("rel", RELS))

# 安全 mode(持続ルールの減衰対象外に相当する概念は「持続重みを掛けない」で表現しない。
# 本実装では危険ルールの重みが持続より十分大きいことで即応性を担保する)
_SAFETY = ("emergency", "alert_required")

# ---------------------------------------------------------------------------
# 決定的擬似乱数(乱数モジュール不使用の再現可能な初期化列)
# ---------------------------------------------------------------------------
def _dseq(seed, n, scale=0.30):
    """seed から決定的に n 個の値を生む(sin ベース・[-scale, scale])。"""
    out = []
    for k in range(n):
        v = math.sin(12.9898 * (seed + 1) + 78.233 * (k + 1)) * 43758.5453
        out.append(((v - math.floor(v)) * 2.0 - 1.0) * scale)
    return out


def _sigmoid(x):
    if x >= 0:
        z = math.exp(-min(x, 30.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -30.0))
    return z / (1.0 + z)


# ---------------------------------------------------------------------------
# ① ニューラル述語: 2層 MLP(入力 d → 隠れ H(tanh) → sigmoid)
# ---------------------------------------------------------------------------
_H = 5  # 隠れユニット数(supreme6: 述語容量の拡大)

# supreme7(ADR 0056-s7): アブレーション研究用フラグ。既定は全 ON(=supreme6 と同一挙動)。
FLAGS = {"pretrain": True, "p2": True, "cost_margin": True, "eg": True,
         "priors": True, "warmstart": True}

# 述語名 → 使用する特徴キー(x はこの順で MLP に入る)
PREDICATES = {
    "ConvEv":   ["speech", "speaking", "range_n"],           # 近接した会話らしさ
    "AddrEv":   ["call_user", "addr_link", "near3", "spk_link"],  # ユーザーへの呼びかけらしさ
    "SpkOnly":  ["spk_link", "addr_link"],                   # speaking リンク優勢(ongoing 証拠)
    "CrowdEv":  ["humans_n", "speaking"],                    # 群衆らしさ
    "NearEv":   ["range_n", "near3"],                        # 至近らしさ
    "SpeechSrc": ["speech", "speaking", "spk_link"],         # 主が発話者らしい
    "HumanSrc": ["humans_n", "speech", "range_n"],           # 主が人らしい
    "ObjSrc":   ["objects_n", "vehicle", "alarm"],           # 主が物体らしい
    "LowQ":     ["h_q"],                                     # 観測品質の劣化
    "UncEv":    ["h_q", "range_n", "spk_link", "speaking"],  # 判定不能らしさ(uncertain)
    "DepEv":    ["t1_depart", "range_n", "approaching"],     # 離脱らしさ(departing)
    "FarEv":    ["range_n", "near3", "humans_n", "spk_link"],# 無関係らしさ(unrelated)
}

# 観測述語(そのまま真理値として使う特徴キー)
OBSERVED = ["siren", "alarm", "vehicle", "speech", "risk_danger", "risk_caution",
            "approaching", "call_user", "addr_link", "spk_link", "humans_n", "objects_n",
            "t1_depart", "t1_pass"]


def _init_mlp(name, d):
    seed = sum(ord(c) for c in name)
    w1 = _dseq(seed, d * _H)
    b1 = _dseq(seed + 101, _H, 0.05)
    w2 = _dseq(seed + 202, _H)
    b2 = [-2.0]  # 未学習の述語はほぼ沈黙(≈0.12)から学習で立ち上げる
    return {"w1": w1, "b1": b1, "w2": w2, "b2": b2, "d": d}


def _mlp_forward(m, x):
    """順伝播。中間値を返す(逆伝播用)。"""
    d, h = m["d"], _H
    hid = []
    for j in range(h):
        s = m["b1"][j]
        for i in range(d):
            s += m["w1"][j * d + i] * x[i]
        hid.append(math.tanh(s))
    z = m["b2"][0]
    for j in range(h):
        z += m["w2"][j] * hid[j]
    return _sigmoid(z), hid


def _mlp_backward(m, x, hid, p, dp, grads):
    """∂loss/∂p = dp を受けて勾配を蓄積する(sigmoid・tanh の手書き逆伝播)。"""
    d, h = m["d"], _H
    dz = dp * p * (1.0 - p)
    g = grads
    g["b2"][0] += dz
    for j in range(h):
        g["w2"][j] += dz * hid[j]
        dh = dz * m["w2"][j] * (1.0 - hid[j] * hid[j])
        g["b1"][j] += dh
        for i in range(d):
            g["w1"][j * d + i] += dh * x[i]


def _zero_like(m):
    return {"w1": [0.0] * len(m["w1"]), "b1": [0.0] * len(m["b1"]),
            "w2": [0.0] * len(m["w2"]), "b2": [0.0]}


# ---------------------------------------------------------------------------
# ② ルールプログラム(Łukasiewicz 緩和の重み付き含意)
#    各ルール: (名前, 初期重み, body=[(atom, 否定?)...], head=(layer, class))
#    atom は 観測述語名 / ニューラル述語名 / ("mode"|"role"|"rel", class) の開述語 /
#    ("prev_mode", class) = 前フレームの mode 開述語(時間持続)
# ---------------------------------------------------------------------------
RULES = [
    # --- mode(supreme2 の規則を事前分布として宣言・重みは学習可)---
    ("r_danger_emerg",   5.0, [("risk_danger", False)],                      ("mode", "emergency")),
    ("r_caut_fwd",       4.0, [("risk_caution", False), ("vehicle", False), ("ConvEv", True)], ("mode", "forward_caution")),
    ("r_caut_side",      4.0, [("risk_caution", False), ("HumanSrc", False), ("ConvEv", True)], ("mode", "side_rear_caution")),
    ("r_caut_alert",     3.0, [("risk_caution", False), ("vehicle", True), ("ConvEv", True)], ("mode", "alert_required")),
    ("r_conv_ongoing",   4.0, [("ConvEv", False)],                           ("mode", "conv_ongoing")),
    ("r_spk_ongoing",    4.0, [("SpkOnly", False)],                          ("mode", "conv_ongoing")),
    ("r_addr_request",   4.0, [("AddrEv", False), ("SpkOnly", True), ("risk_danger", True)], ("mode", "conv_request")),
    ("r_crowd_surround", 4.0, [("CrowdEv", False), ("ConvEv", True)],        ("mode", "surround_activity")),
    ("r_appr_fwd",       4.0, [("approaching", False)],                      ("mode", "forward_caution")),
    ("r_lowq_env",       4.0, [("LowQ", False)],                             ("mode", "env_change")),
    # --- role ---
    ("r_siren_alarm",    2.0, [("siren", False)],                            ("role", "source_alarm")),
    ("r_alarm_alarm",    2.0, [("alarm", False)],                            ("role", "source_alarm")),
    ("r_vehicle_role",   1.5, [("vehicle", False), ("siren", True), ("alarm", True)], ("role", "source_vehicle")),
    ("r_speech_role",    2.0, [("SpeechSrc", False)],                        ("role", "source_speech")),
    ("r_human_role",     1.0, [("HumanSrc", False), ("SpeechSrc", True), ("alarm", True)], ("role", "source_human")),
    ("r_object_role",    1.0, [("ObjSrc", False), ("siren", True)],          ("role", "source_object")),
    # --- relation ---
    ("r_addr_rel",       2.5, [("AddrEv", False)],                           ("rel", "addressing_user")),
    ("r_appr_rel",       2.0, [("approaching", False)],                      ("rel", "approaching")),
    ("r_conv_near",      1.5, [("ConvEv", False)],                           ("rel", "near_user")),
    ("r_crowd_grouped",  2.0, [("CrowdEv", False)],                          ("rel", "grouped")),
    # --- 層間整合(supreme2 ではハードコードだったものの宣言化)---
    ("x_ongoing_speech", 1.0, [(("mode", "conv_ongoing"), False)],           ("role", "source_speech")),
    ("x_emerg_alarm",    1.0, [(("mode", "emergency"), False)],              ("role", "source_alarm")),
    ("x_request_addr",   1.0, [(("mode", "conv_request"), False)],           ("rel", "addressing_user")),
    ("x_surround_group", 1.0, [(("mode", "surround_activity"), False)],      ("rel", "grouped")),
    # --- supreme8: 語彙の壁を壊す新ルール(ADR 0057-s8)---
    ("r_unc_mode",       3.0, [("UncEv", False)],                            ("mode", "uncertain")),
    ("r_t1dep_rel",      3.0, [("t1_depart", False)],                        ("rel", "departing")),
    ("r_depev_rel",      2.0, [("DepEv", False)],                            ("rel", "departing")),
    ("r_far_unrel",      2.0, [("FarEv", False), ("approaching", True)],     ("rel", "unrelated")),
    # --- 時間持続(ヒステリシスの PSL 化): Mode(f-1, m) → Mode(f, m) ---
    ("t_persist_mode",   1.2, [("PREV_MODE", False)],                        ("mode", "*")),
]


def _init_priors():
    return {l: [(_PRIOR_INIT_DEFAULT if (l, c) in _DEFAULT_CLASSES else _PRIOR_INIT_OTHER)
                for c in vs] for l, vs in LAYERS}


@dataclass
class NeuPSLParams:
    """学習対象(ルール重み+クラス別負事前+ニューラル述語 MLP)。決定的に初期化される。"""
    weights: dict = field(default_factory=lambda: {name: w for name, w, _, _ in RULES})
    priors: dict = field(default_factory=_init_priors)
    mlps: dict = field(default_factory=lambda: {
        p: _init_mlp(p, len(keys)) for p, keys in PREDICATES.items()})

    def learnable_param_count(self):
        n = len(self.weights) + sum(len(v) for v in self.priors.values())
        for m in self.mlps.values():
            n += len(m["w1"]) + len(m["b1"]) + len(m["w2"]) + 1
        return n


def default_params():
    return NeuPSLParams()


# ---------------------------------------------------------------------------
# 特徴 → 述語真理値
# ---------------------------------------------------------------------------
def _predicate_values(feat, params):
    """観測述語+ニューラル述語の真理値 dict(と MLP 中間値)を返す。"""
    vals = {k: max(0.0, min(1.0, float(feat.get(k, 0.0)))) for k in OBSERVED}
    inter = {}
    for pname, keys in PREDICATES.items():
        x = [max(0.0, min(1.0, float(feat.get(k, 0.0)))) for k in keys]
        p, hid = _mlp_forward(params.mlps[pname], x)
        vals[pname] = p
        inter[pname] = (x, hid, p)
    return vals, inter


# ---------------------------------------------------------------------------
# ③ 結合 MAP 推論(HL-MRF・射影劣勾配)
# ---------------------------------------------------------------------------
def _atom_value(atom, neg, f, vals_seq, y):
    """atom の真理値と、(開述語なら) y への参照キーを返す。"""
    if atom == "PREV_MODE":
        return None, None  # 持続ルールは _rule_instances で個別展開
    if isinstance(atom, tuple):
        layer, cls = atom
        v = y[f][layer][_IDX[layer][cls]]
        key = (f, layer, _IDX[layer][cls])
    else:
        v = vals_seq[f][atom]
        key = None
    return (1.0 - v if neg else v), key


_IDX = {"mode": {c: i for i, c in enumerate(MODES)},
        "role": {c: i for i, c in enumerate(ROLES)},
        "rel": {c: i for i, c in enumerate(RELS)}}


def _rule_instances(n_frames):
    """フレーム毎に接地したルールインスタンス列を返す。
    要素: (rule_name, f, body=[(atom,neg)...], head=(layer, idx), prev=(f-1,mode_idx)|None)
    """
    inst = []
    for name, _w, body, head in RULES:
        if name == "t_persist_mode":
            for f in range(1, n_frames):
                for mi in range(len(MODES)):
                    inst.append((name, f, None, ("mode", mi), (f - 1, mi)))
        else:
            hl, hc = head
            hi = _IDX[hl][hc]
            for f in range(n_frames):
                inst.append((name, f, body, (hl, hi), None))
    return inst


def _project_simplex(v):
    """v を確率単体(非負・総和1)へ射影する(決定的・ソートベース)。"""
    n = len(v)
    u = sorted(v, reverse=True)
    css = 0.0
    rho, theta = 0, 0.0
    for i in range(n):
        css += u[i]
        t = (css - 1.0) / (i + 1)
        if u[i] - t > 0:
            rho, theta = i + 1, t
    return [max(0.0, x - theta) for x in v]


def _energy_and_grad(inst, weights, vals_seq, y, want_grad_y=True, priors=None):
    """エネルギー E と(必要なら)∂E/∂y を返す。φ(ルール別違反量合計)も返す。"""
    E = 0.0
    phi = {}
    gy = [[[0.0] * len(vs) for _, vs in LAYERS] ] if False else None
    if want_grad_y:
        gy = [{l: [0.0] * len(vs) for l, vs in LAYERS} for _ in range(len(y))]
    for name, f, body, (hl, hi), prev in inst:
        w = weights[name]
        head_v = y[f][hl][hi]
        if prev is not None:
            pf, mi = prev
            body_v = y[pf]["mode"][mi]
            viol = body_v - head_v
            if viol > 0:
                pw2 = viol if FLAGS["p2"] else 1.0
                E += w * viol * pw2
                phi[name] = phi.get(name, 0.0) + viol * pw2
                if want_grad_y:
                    gy[pf]["mode"][mi] += (2.0 if FLAGS["p2"] else 1.0) * w * pw2
                    gy[f][hl][hi] -= (2.0 if FLAGS["p2"] else 1.0) * w * pw2
            continue
        # Łukasiewicz 連言: I(body) = max(0, Σ terms − (k−1))
        s = 0.0
        open_keys = []
        for atom, neg in body:
            v, key = _atom_value(atom, neg, f, vals_seq, y)
            s += v
            if key is not None:
                open_keys.append((key, -1.0 if neg else 1.0))
        body_v = max(0.0, s - (len(body) - 1)) if body else 1.0
        viol = body_v - head_v
        if viol > 0:
            pw2 = viol if FLAGS["p2"] else 1.0
            E += w * viol * pw2
            phi[name] = phi.get(name, 0.0) + viol * pw2
            if want_grad_y:
                gfac = (2.0 if FLAGS["p2"] else 1.0) * w * pw2
                gy[f][hl][hi] -= gfac
                if body and body_v > 0:
                    for (kf, kl, ki), sign in open_keys:
                        gy[kf][kl][ki] += gfac * sign
    # クラス別負事前 + Tikhonov(いずれも二乗項): E += (p_c + ε)·y_c²
    if priors is not None:
        for f in range(len(y)):
            for l, vs in LAYERS:
                pv = priors[l]
                for i in range(len(vs)):
                    yv = y[f][l][i]
                    E += (pv[i] + _EPS_TIK) * yv * yv
                    if want_grad_y:
                        gy[f][l][i] += 2.0 * (pv[i] + _EPS_TIK) * yv
    return E, gy, phi


_LAYER_LOSS_W = {"mode": 1.0, "role": 1.0, "rel": 1.0}  # コスト感応マージンに役割を移譲
_EPS_TIK = 0.005      # εI Tikhonov(ICML2024: MAP の一意化・Lipschitz 化)
_MARGIN_BASE = 0.6    # コスト感応マージンの基準値(層別×クラス逆頻度で変調)
_PRIOR_INIT_DEFAULT = 0.01   # 旧既定クラス(quiet/unknown/grouped)の負事前
_PRIOR_INIT_OTHER = 0.08     # その他クラスの負事前(証拠が無ければ出ない)
_DEFAULT_CLASSES = {("mode", "quiet_standby"), ("role", "unknown"), ("rel", "grouped")}
_LAYER_MARGIN = {"mode": 0.8, "role": 0.8, "rel": 0.8}  # 層別マージン(loss-augmented 推論)  # 層別の損失重み(崩れの大きい層を強調)


def map_inference(vals_seq, params, iters=160, margin_gt=None, init=None, prox=None):
    """シナリオ単位の結合 MAP。y[f][layer] = クラス確率(単体上)を返す。"""
    n = len(vals_seq)
    if init is not None:
        y = [{l: list(init[f][l]) for l, _vs in LAYERS} for f in range(n)]
    else:
        y = [{l: [1.0 / len(vs)] * len(vs) for l, vs in LAYERS} for _ in range(n)]
    inst = _rule_instances(n)
    for t in range(iters):
        eta = 0.20 / math.sqrt(1.0 + t * 0.15)
        _E, gy, _ = _energy_and_grad(inst, params.weights, vals_seq, y,
                                     priors=params.priors)
        if margin_gt:
            # コスト感応 loss-augmented: E(y) − Σ c_v·Δ を最小化(係数=層別×クラス逆頻度)
            for (mf, ml, mi, coef) in margin_gt:
                gy[mf][ml][mi] += coef
        if prox is not None:
            # Moreau 包絡: E(y) + (1/2ρ)·‖y − ŷ‖² の最小化(bilevel BCE 用)
            yhat, rho = prox
            inv_rho = 1.0 / rho
            for f in range(n):
                for l, vs in LAYERS:
                    for i in range(len(vs)):
                        gy[f][l][i] += inv_rho * (y[f][l][i] - yhat[f][l][i])
        delta = 0.0
        for f in range(n):
            for l, vs in LAYERS:
                blk = [y[f][l][i] - eta * gy[f][l][i] for i in range(len(vs))]
                blk = _project_simplex(blk)
                for i in range(len(vs)):
                    d = blk[i] - y[f][l][i]
                    if d > delta or -d > delta:
                        delta = d if d > 0 else -d
                y[f][l] = blk
        if t > 24 and delta < 1e-3:  # 決定的な早期収束打ち切り
            break
    return y


def _argmax(vals, names):
    bi, bv = 0, vals[0]
    for i in range(1, len(vals)):
        if vals[i] > bv + 1e-12:
            bi, bv = i, vals[i]
    return names[bi]


def infer_scenario(feats_seq, params=None, iters=200):
    """フレーム特徴列 → 各フレームの {mode, role, rel} ラベル(決定的)。"""
    params = params or default_params()
    vals_seq = [_predicate_values(f, params)[0] for f in feats_seq]
    y = map_inference(vals_seq, params, iters=iters)
    out = []
    for f in range(len(feats_seq)):
        out.append({"mode": _argmax(y[f]["mode"], MODES),
                    "role": _argmax(y[f]["role"], ROLES),
                    "rel": _argmax(y[f]["rel"], RELS)})
    return out


# ---------------------------------------------------------------------------
# ④ 学習(構造化パーセプトロン: E(GT) − E(MAP) を下げる)
# ---------------------------------------------------------------------------
# 述語 → GT からの蒸留ターゲット(該当層のラベルが無いフレームは学習対象外)
_PRED_TARGET = {
    "ConvEv":   lambda g: None if g.get("mode") is None else (1.0 if g["mode"] == "conv_ongoing" else 0.0),
    "AddrEv":   lambda g: None if g.get("rel") is None else (1.0 if g["rel"] == "addressing_user" else 0.0),
    "SpkOnly":  lambda g: None if g.get("mode") is None else (1.0 if g["mode"] == "conv_ongoing" else 0.0),
    "CrowdEv":  lambda g: None if g.get("mode") is None else (1.0 if g["mode"] == "surround_activity" else 0.0),
    "NearEv":   lambda g: None if g.get("rel") is None else (1.0 if g["rel"] == "near_user" else 0.0),
    "SpeechSrc": lambda g: None if g.get("role") is None else (1.0 if g["role"] == "source_speech" else 0.0),
    "HumanSrc": lambda g: None if g.get("role") is None else (1.0 if g["role"] == "source_human" else 0.0),
    "ObjSrc":   lambda g: None if g.get("role") is None else (1.0 if g["role"] == "source_object" else 0.0),
    "LowQ":     lambda g: None if g.get("mode") is None else (1.0 if g["mode"] == "env_change" else 0.0),
    "UncEv":    lambda g: None if g.get("mode") is None else (1.0 if g["mode"] == "uncertain" else 0.0),
    "DepEv":    lambda g: None if g.get("rel") is None else (1.0 if g["rel"] == "departing" else 0.0),
    "FarEv":    lambda g: None if g.get("rel") is None else (1.0 if g["rel"] == "unrelated" else 0.0),
}


def pretrain_predicates(scenarios, params, steps=400, lr=0.5):
    """ニューラル述語をラベル蒸留(BCE・full-batch GD)で事前学習する(決定的)。

    NeuPSL の標準手順「ラベルで事前学習 → joint は極小 lr」(引用NW: lr比 ~1/10⁴)に倣う。
    """
    data = {pname: [] for pname in PREDICATES}
    for feats_seq, gt_seq in scenarios:
        for i, feat in enumerate(feats_seq):
            g = gt_seq[i] if i < len(gt_seq) else {}
            for pname, keys in PREDICATES.items():
                t = _PRED_TARGET[pname](g)
                if t is None:
                    continue
                data[pname].append(([max(0.0, min(1.0, float(feat.get(k, 0.0)))) for k in keys], t))
    for pname, rows in data.items():
        if not rows:
            continue
        m = params.mlps[pname]
        pos = sum(t for _x, t in rows)
        w_pos = (len(rows) - pos) / max(pos, 1.0)  # 不均衡補正(陽性の重み)
        w_pos = min(w_pos, 50.0)
        inv = 1.0 / len(rows)
        for _st in range(steps):
            g = _zero_like(m)
            for x, t in rows:
                pr, hid = _mlp_forward(m, x)
                dp = (pr - t) * (w_pos if t > 0.5 else 1.0) * inv
                # BCE 勾配 ∂L/∂z = p − t → _mlp_backward は dp·p(1−p) を掛けるため補正
                dz_over = dp / max(pr * (1.0 - pr), 1e-4)
                _mlp_backward(m, x, hid, pr, dz_over, g)
            for key in ("w1", "b1", "w2", "b2"):
                for i in range(len(m[key])):
                    m[key][i] -= lr * g[key][i]
    return params


def _margin_coefs(scenarios):
    """コスト感応マージン係数: 層別基準 × クラス逆頻度(正規化・[0.25, 4] にクリップ)。"""
    counts = {l: [1.0] * len(vs) for l, vs in LAYERS}
    for _feats, gts in scenarios:
        for g in gts:
            for l, _vs in LAYERS:
                lab = g.get(l)
                if lab in _IDX[l]:
                    counts[l][_IDX[l][lab]] += 1.0
    coefs = {}
    for l, vs in LAYERS:
        inv = [1.0 / c for c in counts[l]]
        mean = sum(inv) / len(inv)
        coefs[l] = [_MARGIN_BASE * max(0.25, min(4.0, v / mean)) for v in inv]
    return coefs


def _gt_assignment(y_map, gt_seq):
    """GT ラベルを one-hot 化した割当(語彙外/None は MAP 値を流用=その項は中立)。"""
    y = []
    for f, gt in enumerate(gt_seq):
        blk = {}
        for l, vs in LAYERS:
            lab = gt.get(l)
            if lab in _IDX[l]:
                v = [0.0] * len(vs)
                v[_IDX[l][lab]] = 1.0
            else:
                v = list(y_map[f][l])
            blk[l] = v
        y.append(blk)
    return y


_W_MAX = 8.0  # ルール重みの上限(重み爆発の抑止・PSL の正則化に相当)


def fit(scenarios, params=None, epochs=2, lr_w=0.4, lr_n=0.006, lr_p=0.02,
        average=True, map_iters=110, pretrain=True):
    """scenarios: [(feats_seq, gt_seq)] を決定的順序で学習し NeuPSLParams を返す。

    gt_seq: [{"mode": ラベル|None, "role": ..., "rel": ...}, ...]

    安定化(いずれも決定的): φ はフレーム数で正規化 / 重みは [0, _W_MAX] にクリップ /
    平均化パーセプトロン(更新ごとのパラメータ平均を最終結果とする)。
    """
    if params is None:
        params = default_params()
        if pretrain and FLAGS["pretrain"]:
            pretrain_predicates(scenarios, params)
    rule_lw = {name: _LAYER_LOSS_W[head[0]] for name, _w, _b, head in RULES
               if head[1] != "*"}
    rule_lw["t_persist_mode"] = _LAYER_LOSS_W["mode"]
    mcoef = _margin_coefs(scenarios) if FLAGS["cost_margin"] else {l: [_MARGIN_BASE]*len(vs) for l, vs in LAYERS}
    total_mass = sum(w for _n, w, _b, _h in RULES)
    ws_cache = [None] * len(scenarios)
    avg_w = {k: 0.0 for k in params.weights}
    avg_p = {l: [0.0] * len(vs) for l, vs in LAYERS}
    avg_m = {p_: _zero_like(m) for p_, m in params.mlps.items()}
    n_avg = 0
    for _ep in range(epochs):
        dec = 1.0 / math.sqrt(1.0 + _ep)  # エポック毎の学習率減衰
        for _si, (feats_seq, gt_seq) in enumerate(scenarios):
            n = len(feats_seq)
            if n == 0:
                continue
            pv = [_predicate_values(f, params) for f in feats_seq]
            vals_seq = [p[0] for p in pv]
            inter_seq = [p[1] for p in pv]
            inst = _rule_instances(n)
            mgt = []
            for f, gtf in enumerate(gt_seq):
                for l, _vs in LAYERS:
                    lab = gtf.get(l)
                    if lab in _IDX[l]:
                        ci = _IDX[l][lab]
                        mgt.append((f, l, ci, mcoef[l][ci]))
            y_map = map_inference(vals_seq, params, iters=map_iters, margin_gt=mgt,
                                  init=ws_cache[_si] if FLAGS["warmstart"] else None)
            ws_cache[_si] = [{l: list(y_map[f][l]) for l, _vs in LAYERS}
                             for f in range(len(y_map))]
            y_gt = _gt_assignment(y_map, gt_seq)
            _, _, phi_map = _energy_and_grad(inst, params.weights, vals_seq, y_map, want_grad_y=False)
            _, _, phi_gt = _energy_and_grad(inst, params.weights, vals_seq, y_gt, want_grad_y=False)
            # 負事前の φ(= Σ y_c²)
            pp_gt = {l: [0.0] * len(vs) for l, vs in LAYERS}
            pp_map = {l: [0.0] * len(vs) for l, vs in LAYERS}
            for f in range(n):
                for l, vs in LAYERS:
                    for i in range(len(vs)):
                        pp_gt[l][i] += y_gt[f][l][i] ** 2
                        pp_map[l][i] += y_map[f][l][i] ** 2
            # --- ルール重み更新: 単体制約(総質量固定)上の正規化指数勾配 + log バリア ---
            inv_n = 1.0 / n
            lam = 1e-3
            if FLAGS["eg"]:
                neww = {}
                for name, wv in params.weights.items():
                    g = (phi_gt.get(name, 0.0) - phi_map.get(name, 0.0)) * inv_n * rule_lw[name]
                    g -= lam / max(wv, 1e-6)
                    ex = -lr_w * dec * g
                    neww[name] = max(wv, 1e-6) * math.exp(max(-2.0, min(2.0, ex)))
                zs = sum(neww.values())
                for name in neww:
                    params.weights[name] = total_mass * neww[name] / zs
            else:
                for name, wv in params.weights.items():
                    g = (phi_gt.get(name, 0.0) - phi_map.get(name, 0.0)) * inv_n * rule_lw[name]
                    params.weights[name] = min(8.0, max(0.0, wv - 0.05 * dec * g))
            # --- 負事前の更新(小さな SGD・[0, 0.5] クリップ)---
            if FLAGS["priors"]:
                for l, vs in LAYERS:
                    pv = params.priors[l]
                    for i in range(len(vs)):
                        gp = (pp_gt[l][i] - pp_map[l][i]) * inv_n
                        pv[i] = min(0.5, max(0.0, pv[i] - lr_p * dec * gp))
            # --- ニューラル述語更新: ∂[E(gt) − E(map)]/∂θ ---
            grads = {p: _zero_like(m) for p, m in params.mlps.items()}
            for y_ass, sign in ((y_gt, 1.0), (y_map, -1.0)):
                for name, f, body, (hl, hi), prev in inst:
                    if prev is not None or not body:
                        continue
                    w = params.weights[name]
                    s = 0.0
                    terms = []
                    for atom, neg in body:
                        v, _k = _atom_value(atom, neg, f, vals_seq, y_ass)
                        s += v
                        terms.append((atom, neg))
                    body_v = s - (len(body) - 1)
                    viol = body_v - y_ass[f][hl][hi]
                    if body_v > 0 and viol > 0:
                        for atom, neg in terms:
                            if isinstance(atom, str) and atom in PREDICATES:
                                x, hid, p = inter_seq[f][atom]
                                dp = sign * w * (-1.0 if neg else 1.0) * rule_lw[name]
                                _mlp_backward(params.mlps[atom], x, hid, p, dp, grads[atom])
            for pname, m in params.mlps.items():
                g = grads[pname]
                for key in ("w1", "b1", "w2", "b2"):
                    for i in range(len(m[key])):
                        m[key][i] -= lr_n * dec * g[key][i] * inv_n
            # --- 平均化パーセプトロン(最終エポックのみ累積: 序盤の沈黙期を含めない)---
            if not average or _ep != epochs - 1:
                continue
            n_avg += 1
            for k in params.weights:
                avg_w[k] += params.weights[k]
            for l, vs in LAYERS:
                for i in range(len(vs)):
                    avg_p[l][i] += params.priors[l][i]

    if n_avg:
        out = NeuPSLParams()
        out.mlps = params.mlps  # MLP は最終値(平均は重み/prior のみ。事前学習を保持)
        out.weights = {k: avg_w[k] / n_avg for k in avg_w}
        out.priors = {l: [avg_p[l][i] / n_avg for i in range(len(vs))] for l, vs in LAYERS}
        return out
    return params


# ---------------------------------------------------------------------------
# bilevel BCE(NeSy-EBM の minimizer-based 損失の簡略実装・ADR 0054-s5)
#   min_{w,ŷ}  BCE(ŷ, GT) + μ·max(M_ρ(ŷ; w) − V(w), 0)²
#   M_ρ(ŷ) = min_ỹ E(ỹ) + (1/2ρ)‖ỹ−ŷ‖²(Moreau 包絡・∇_ŷM = (ŷ−prox)/ρ)
#   ∇_w は包絡定理より Φ(prox) − Φ(y*_free) に比例。決定的(乱数・時刻なし)。
# ---------------------------------------------------------------------------
def fit_bilevel(scenarios, params, epochs=1, rho=0.6, mu=2.0, lr_y=0.3, lr_w=0.2,
                lr_n=0.004, lr_p=0.01, y_steps=3, prox_iters=40, free_iters=90,
                average=False):
    """supreme4 レシピで学習済みの params を bilevel BCE で微調整する。"""
    avg_w = {k: 0.0 for k in params.weights}
    avg_p = {l: [0.0] * len(vs) for l, vs in LAYERS}
    n_avg = 0
    free_cache = [None] * len(scenarios)
    yhat_cache = [None] * len(scenarios)
    for _ep in range(epochs):
        for _si, (feats_seq, gt_seq) in enumerate(scenarios):
            n = len(feats_seq)
            if n == 0:
                continue
            pv = [_predicate_values(f, params) for f in feats_seq]
            vals_seq = [x[0] for x in pv]
            inter_seq = [x[1] for x in pv]
            inst = _rule_instances(n)
            y_free = map_inference(vals_seq, params, iters=free_iters,
                                   init=free_cache[_si])
            free_cache[_si] = [{l: list(y_free[f][l]) for l, _v in LAYERS} for f in range(n)]
            yhat = yhat_cache[_si] or [{l: list(y_free[f][l]) for l, _v in LAYERS}
                                       for f in range(n)]
            E_free, _, phi_free = _energy_and_grad(inst, params.weights, vals_seq,
                                                   y_free, want_grad_y=False,
                                                   priors=params.priors)
            prox_y = yhat
            for _k in range(y_steps):
                prox_y = map_inference(vals_seq, params, iters=prox_iters,
                                       init=prox_y, prox=(yhat, rho))
                E_prox, _, _ = _energy_and_grad(inst, params.weights, vals_seq,
                                                prox_y, want_grad_y=False,
                                                priors=params.priors)
                dist = sum((yhat[f][l][i] - prox_y[f][l][i]) ** 2
                           for f in range(n) for l, vs in LAYERS
                           for i in range(len(vs)))
                pen = max(0.0, (E_prox + dist / (2.0 * rho)) - E_free)
                # ŷ 更新: ∇BCE + μ·2·pen·(ŷ − prox)/ρ → 単体射影
                for f in range(n):
                    gtf = gt_seq[f] if f < len(gt_seq) else {}
                    for l, vs in LAYERS:
                        lab = gtf.get(l)
                        if lab not in _IDX[l]:
                            continue
                        ti = _IDX[l][lab]
                        blk = list(yhat[f][l])
                        for i in range(len(vs)):
                            yv = min(0.999, max(0.001, blk[i]))
                            dbce = (-1.0 / yv if i == ti else 1.0 / (1.0 - yv)) / len(vs)
                            gpen = mu * 2.0 * pen * (blk[i] - prox_y[f][l][i]) / rho
                            blk[i] -= lr_y * (dbce + gpen)
                        yhat[f][l] = _project_simplex(blk)
            yhat_cache[_si] = yhat
            # --- w / prior / MLP 更新: 係数 = μ·2·pen、Δφ = φ(prox) − φ(free) ---
            _, _, phi_prox = _energy_and_grad(inst, params.weights, vals_seq,
                                              prox_y, want_grad_y=False,
                                              priors=params.priors)
            coef = mu * 2.0 * pen / n
            neww = {}
            lam = 1e-3
            total_mass = sum(w for _n2, w, _b, _h in RULES)
            for name, wv in params.weights.items():
                g = coef * (phi_prox.get(name, 0.0) - phi_free.get(name, 0.0))
                g -= lam / max(wv, 1e-6)
                neww[name] = max(wv, 1e-6) * math.exp(max(-2.0, min(2.0, -lr_w * g)))
            zs = sum(neww.values())
            for name in neww:
                params.weights[name] = total_mass * neww[name] / zs
            for l, vs in LAYERS:
                pvr = params.priors[l]
                for i in range(len(vs)):
                    gp = coef * sum(prox_y[f][l][i] ** 2 - y_free[f][l][i] ** 2
                                    for f in range(n))
                    pvr[i] = min(0.5, max(0.0, pvr[i] - lr_p * gp))
            grads = {q: _zero_like(m) for q, m in params.mlps.items()}
            for y_ass, sign in ((prox_y, 1.0), (y_free, -1.0)):
                for name, f, body, (hl, hi), prev in inst:
                    if prev is not None or not body:
                        continue
                    w = params.weights[name]
                    sfull = 0.0
                    terms = []
                    for atom, neg in body:
                        v, _k2 = _atom_value(atom, neg, f, vals_seq, y_ass)
                        sfull += v
                        terms.append((atom, neg))
                    body_v = sfull - (len(body) - 1)
                    viol = body_v - y_ass[f][hl][hi]
                    if body_v > 0 and viol > 0:
                        for atom, neg in terms:
                            if isinstance(atom, str) and atom in PREDICATES:
                                x, hid, prb = inter_seq[f][atom]
                                dp = sign * coef * 2.0 * w * viol * (-1.0 if neg else 1.0)
                                _mlp_backward(params.mlps[atom], x, hid, prb, dp, grads[atom])
            for q, m in params.mlps.items():
                g = grads[q]
                for key in ("w1", "b1", "w2", "b2"):
                    for i in range(len(m[key])):
                        m[key][i] -= lr_n * g[key][i]
            if average:
                n_avg += 1
                for k in params.weights:
                    avg_w[k] += params.weights[k]
                for l, vs in LAYERS:
                    for i in range(len(vs)):
                        avg_p[l][i] += params.priors[l][i]
    if average and n_avg:
        out = NeuPSLParams()
        out.mlps = params.mlps
        out.weights = {k: avg_w[k] / n_avg for k in avg_w}
        out.priors = {l: [avg_p[l][i] / n_avg for i in range(len(vs))] for l, vs in LAYERS}
        return out
    return params
