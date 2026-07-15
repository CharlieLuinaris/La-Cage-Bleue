const fs = require("node:fs");
const path = require("node:path");

const root = __dirname;

// Linux 部署优先使用项目虚拟环境中的 Python；如需自定义，可在启动 PM2 前设置 PYTHON。
const localPython = path.join(root, ".venv", "bin", "python");

const python = process.env.PYTHON || (fs.existsSync(localPython) ? localPython : "python3");

module.exports = {
  apps: [
    {
      name: "la-cage-bleue",
      cwd: root,
      script: python,
      args: "-m captivity_simulator.server",
      interpreter: "none",
      env: {
        NODE_ENV: "production",
        CAGE_HOST: "127.0.0.1",
        CAGE_PORT: "5058",
        CAPTIVITY_CONFIG: path.join(root, "config", "local.json"),
        CAPTIVITY_DATA_DIR: path.join(root, "data"),
      },
    },
  ],
};


