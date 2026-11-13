# 上传 GitHub 前的检查

本机 API Key 保存在 `.local/deepseek.json`。这是本机私有配置，不属于交付代码。`.gitignore` 已排除 `.local/`、`.env` 类配置、数据库和运行日志。

## 使用 Git 提交

提交前检查 `git status --short` 和 `git diff --cached --name-only`，确认待提交列表没有 `.local/`、`.env`、个人简历和训练数据库。不要使用 `git add -f` 强制加入私有文件。

`.gitignore` 不会移除已经跟踪或提交过的文件。若密钥曾经提交，先在 DeepSeek 控制台撤销并重新生成，再移除跟踪文件并处理历史。

## 网页上传或打包交付

网页拖拽上传、网盘分享和压缩软件不会因为存在 `.gitignore` 就自动排除私有文件。不要把整个项目目录直接打包上传。

可上传源代码、`public/`、`tests/`、`docs/`、`.gitignore`、`requirements.txt`、`README.md` 和确认过的报告。不要上传 `.local/`、`data/`、`__pycache__/`、环境文件或包含密钥的截图。

项目在没有密钥时也可用本地规则模式运行；其他成员需要 AI 功能时，在自己的电脑运行 `python server.py --save-api-key`，输入各自的密钥。
