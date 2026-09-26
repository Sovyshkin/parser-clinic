const path = require("node:path");

const projectDir = __dirname;

module.exports = {
  apps: [
    {
      name: "clinic-parser-bot",
      script: path.join(projectDir, "main.py"),
      cwd: projectDir,
      interpreter: path.join(projectDir, ".venv", "bin", "python"),
      exec_mode: "fork",
      instances: 1,
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 15000,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONDONTWRITEBYTECODE: "1",
      },
    },
  ],
};
