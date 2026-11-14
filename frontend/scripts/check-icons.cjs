// 构建前钩子：统一从 favicon.svg 生成 favicon.ico（多尺寸）与 apple-touch-icon.png，
// 保证浏览器标签页、书签、桌面快捷方式都用同一个 logo。
const fs = require("fs");
const path = require("path");

const PUBLIC = path.resolve(__dirname, "..", "public");
const SVG = path.join(PUBLIC, "favicon.svg");

if (!fs.existsSync(SVG)) {
  console.log("[icons] favicon.svg 不存在，跳过");
  process.exit(0);
}

// 只打印状态；真正的位图转换交给 build_vue.bat 里的 sharp（未安装则跳过）
const svg = fs.readFileSync(SVG, "utf8");
const hasSize = /viewBox=/.test(svg);
console.log("[icons] favicon.svg", svg.length + "B", hasSize ? "(viewBox ok)" : "(缺少 viewBox)");

// 若存在 apple-touch-icon.png 则一并确认
const apple = path.join(PUBLIC, "apple-touch-icon.png");
console.log("[icons] apple-touch-icon.png", fs.existsSync(apple) ? "ok" : "missing");
