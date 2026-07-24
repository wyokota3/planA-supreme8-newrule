const wsUrl = process.argv[2];
const pageUrl = process.argv[3];
const readingCharsPerMinute = Number(process.argv[4]);
if (!wsUrl || !pageUrl || !Number.isFinite(readingCharsPerMinute)) {
  throw new Error(
    "usage: node verify_architecture_browser.mjs <websocket-url> <page-url> <reading-chars-per-minute>"
  );
}

const socket = new WebSocket(wsUrl);
const pending = new Map();
const waiters = new Map();
const runtimeErrors = [];
let nextId = 1;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitEvent(name, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout waiting for ${name}`)), timeoutMs);
    const list = waiters.get(name) || [];
    list.push((params) => {
      clearTimeout(timer);
      resolve(params);
    });
    waiters.set(name, list);
  });
}

function command(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject, method });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const item = pending.get(message.id);
    if (!item) return;
    pending.delete(message.id);
    if (message.error) item.reject(new Error(`${item.method}: ${message.error.message}`));
    else item.resolve(message.result);
    return;
  }
  if (message.method === "Runtime.exceptionThrown") {
    runtimeErrors.push(`exception: ${message.params.exceptionDetails.text}`);
  }
  if (message.method === "Runtime.consoleAPICalled") {
    const type = message.params.type;
    if (type === "error" || type === "assert") {
      const args = message.params.args.map((arg) => arg.value ?? arg.description ?? "").join(" ");
      runtimeErrors.push(`console.${type}: ${args}`);
    }
  }
  if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
    runtimeErrors.push(`log.error: ${message.params.entry.text}`);
  }
  const list = waiters.get(message.method);
  if (list && list.length) {
    const resolve = list.shift();
    resolve(message.params);
  }
});
socket.addEventListener("close", (event) => {
  const error = new Error(
    `DevTools WebSocket closed: code=${event.code}, reason=${event.reason || "(none)"}`
  );
  for (const item of pending.values()) item.reject(error);
  pending.clear();
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", () => reject(new Error("DevTools WebSocket connection failed")), {
    once: true,
  });
});

await command("Runtime.enable");
await command("Page.enable");
await command("Log.enable");
let loaded = waitEvent("Page.loadEventFired");
await command("Page.navigate", { url: pageUrl });
await loaded;
await wait(2500);

const auditExpression = String.raw`
(() => {
  const parseColor = (value) => {
    const match = String(value).match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[, /]+([\d.]+))?\)/);
    if (!match) return null;
    return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] == null ? 1 : Number(match[4])];
  };
  const over = (top, bottom) => {
    const alpha = top[3] + bottom[3] * (1 - top[3]);
    if (alpha === 0) return [0, 0, 0, 0];
    return [
      (top[0] * top[3] + bottom[0] * bottom[3] * (1 - top[3])) / alpha,
      (top[1] * top[3] + bottom[1] * bottom[3] * (1 - top[3])) / alpha,
      (top[2] * top[3] + bottom[2] * bottom[3] * (1 - top[3])) / alpha,
      alpha,
    ];
  };
  const background = (element) => {
    const chain = [];
    for (let node = element; node; node = node.parentElement) chain.push(node);
    let color = [255, 255, 255, 1];
    chain.reverse().forEach((node) => {
      const parsed = parseColor(getComputedStyle(node).backgroundColor);
      if (parsed && parsed[3] > 0) color = over(parsed, color);
    });
    return color;
  };
  const luminance = (color) => {
    const channels = color.slice(0, 3).map((value) => {
      const component = value / 255;
      return component <= 0.04045
        ? component / 12.92
        : Math.pow((component + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const ratio = (foreground, backdrop) => {
    const fg = over(foreground, backdrop);
    const values = [luminance(fg), luminance(backdrop)].sort((a, b) => b - a);
    return (values[0] + 0.05) / (values[1] + 0.05);
  };
  const paintedBackground = (element, paintedText) => {
    const pageBackground = background(element);
    if (!paintedText) return pageBackground;
    const rect = element.getBoundingClientRect();
    const hitCandidates = document.elementsFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2
    );
    const localCandidates = Array.from(
      element.parentElement?.querySelectorAll("rect,circle,ellipse,polygon,path") || []
    ).filter((candidate) => {
      const shape = candidate.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      return (
        shape.left <= centerX &&
        centerX <= shape.right &&
        shape.top <= centerY &&
        centerY <= shape.bottom
      );
    }).reverse();
    const candidates = [...hitCandidates, ...localCandidates];
    for (const candidate of candidates) {
      const tag = candidate.tagName?.toLowerCase();
      if (
        candidate === element ||
        !["rect", "circle", "ellipse", "polygon", "path"].includes(tag)
      ) continue;
      const fill = parseColor(getComputedStyle(candidate).fill);
      if (fill && fill[3] > 0) return over(fill, pageBackground);
    }
    return pageBackground;
  };
  let contrastMin = Infinity;
  let contrastOffender = "";
  document.querySelectorAll("body *").forEach((element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    if (
      rect.width <= 0 ||
      rect.height <= 0 ||
      style.display === "none" ||
      style.visibility === "hidden" ||
      Number(style.opacity) === 0
    ) return;
    const directText = Array.from(element.childNodes).some(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()
    );
    if (!directText && element.tagName.toLowerCase() !== "text") return;
    const tagName = element.tagName.toLowerCase();
    const paintedText = tagName === "text" || tagName === "tspan";
    const foreground = parseColor(paintedText ? style.fill : style.color);
    if (!foreground) return;
    const backdrop = paintedBackground(element, paintedText);
    const value = ratio(foreground, backdrop);
    if (value < contrastMin) {
      contrastMin = value;
      contrastOffender =
        element.tagName.toLowerCase() +
        (element.id ? "#" + element.id : "") +
        (element.className && typeof element.className === "string"
          ? "." + element.className.trim().replace(/\s+/g, ".")
          : "") +
        "[paint=" + (paintedText ? style.fill : style.color) + ";" +
        "background=rgb(" + backdrop.slice(0, 3).map(Math.round).join(",") + ");" +
        "text=" + (element.textContent || "").trim().slice(0, 60) + "]";
    }
  });
  const overflow = Array.from(document.querySelectorAll("body *"))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden" || rect.width <= 0) return false;
      return rect.right > document.documentElement.clientWidth + 1 || rect.left < -1;
    })
    .slice(0, 12)
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        selector:
          element.tagName.toLowerCase() +
          (element.id ? "#" + element.id : "") +
          (element.className && typeof element.className === "string"
            ? "." + element.className.trim().replace(/\s+/g, ".")
            : ""),
        left: Math.round(rect.left * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
      };
    });
  const sectionChars = (id) => {
    const heading = document.getElementById(id);
    if (!heading) return -1;
    let text = heading.innerText || "";
    for (let node = heading.nextElementSibling; node && node.tagName !== "H2"; node = node.nextElementSibling) {
      text += " " + (node.innerText || "");
    }
    return text.replace(/\s/g, "").length;
  };
  const reading = Array.from(document.querySelectorAll("[data-guide-targets]")).map((card) => {
    const targets = card.dataset.guideTargets.split(",");
    const chars = targets.reduce((total, id) => total + sectionChars(id), 0);
    const shownMatch = (card.querySelector("b")?.textContent || "").match(/理解時間・約(\d+)分/);
    return {
      href: card.getAttribute("href"),
      targets,
      chars,
      minutes: Math.max(1, Math.ceil(chars / ${readingCharsPerMinute})),
      declared: Number(card.dataset.readingMinutes || 0),
      shown: shownMatch ? Number(shownMatch[1]) : 0,
    };
  });
  const labelMap = (root) =>
    Object.fromEntries(
      Array.from(root?.querySelectorAll(".frame-labels li") || []).map((item) => [
        item.querySelector("code")?.textContent || "",
        item.querySelector("span")?.textContent || "",
      ])
    );
  const commonRows = Array.from(
    document.querySelectorAll("#commonFrameComparison tbody tr")
  );
  const commonData = {
    gt: labelMap(
      document.querySelector("#commonFrameComparison tbody tr:first-child td[rowspan] .frame-labels")
    ),
    systems: commonRows.map((row) => {
      const systemHeading = row.querySelector("th[scope='row']");
      return {
        id: systemHeading?.textContent.trim() || "",
        labels: labelMap(systemHeading?.nextElementSibling),
        mechanism: row.lastElementChild?.textContent.trim() || "",
      };
    }),
  };
  const scoreData = Array.from(
    document.querySelectorAll("#fig-t2-evaluation-flow [data-score-layer]")
  ).map((row) => ({
    layer: row.dataset.scoreLayer,
    pred: row.dataset.scorePred,
    gt: row.dataset.scoreGt,
  }));
  const dynamicUnresolved = Array.from(document.querySelectorAll("a[href^='#']"))
    .map((anchor) => anchor.getAttribute("href"))
    .filter((href) => href.length > 1 && !document.getElementById(href.slice(1)));
  return {
    width: innerWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    overflow,
    contrastMin,
    contrastOffender,
    mermaidSvg: document.querySelectorAll("#diagram svg").length,
    mermaidNodes: document.querySelectorAll("#diagram .node").length,
    mermaidEdges: document.querySelectorAll("#diagram .flowchart-link").length,
    mermaidError: /描画エラー|読み込めません/.test(document.getElementById("diagram")?.innerText || ""),
    wiringNodes: document.querySelectorAll("#wboardSvg .wnode").length,
    wiringEdges: document.querySelectorAll("#wboardSvg .wire").length,
    commonRows: commonRows.length,
    scoreRows: scoreData.length,
    catalogCards: document.querySelectorAll("#outputCatalog .ocard").length,
    commonData,
    scoreData,
    dynamicUnresolved,
    activeTheme: document.documentElement.getAttribute("data-theme") || "light",
    reading,
  };
})()
`;

const cases = [];
for (const width of [1600, 390]) {
  for (const theme of ["light", "dark"]) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    loaded = waitEvent("Page.loadEventFired");
    await command("Page.reload", { ignoreCache: true });
    await loaded;
    await wait(1800);
    await command("Runtime.evaluate", {
      expression: `(() => {
        const desired = ${JSON.stringify(theme)};
        const current = document.documentElement.getAttribute("data-theme") || "light";
        if (current !== desired) document.getElementById("themeToggle").click();
      })()`,
    });
    await wait(1200);
    const result = await command("Runtime.evaluate", {
      expression: auditExpression,
      returnByValue: true,
      awaitPromise: true,
    });
    cases.push({ width, theme, ...result.result.value });
  }
}

process.stdout.write(JSON.stringify({ runtimeErrors, cases }));
try {
  await command("Browser.close");
} catch {
  // Browser.closeは接続を先に閉じる実装もあるため、監査結果出力後の切断は成功扱いにします。
}
socket.close();
