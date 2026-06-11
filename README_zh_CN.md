# linux-doc2ima

这是一个 Codex skill，用于从 lore.kernel.org 上的
`linux-doc@vger.kernel.org` 邮件列表归档中抓取 Linux kernel 文档相关补丁邮件，
并可选择将新保存的补丁上传到 IMA 知识库。

## Skill 目录

skill 位于 [`fetch-linux-doc-patches/`](fetch-linux-doc-patches/)。

目录内容包括：

- `SKILL.md`：面向 Codex 的使用说明和触发元数据。
- `scripts/fetch_linux_doc_patches.py`：通过 NNTP 抓取补丁邮件，并可选上传到 IMA。
- `references/scheduling.md`：cron、systemd 和 launchd 的定时任务示例。
- `agents/openai.yaml`：Codex skill 列表展示所需的 UI 元数据。

## 安装

克隆本仓库后，将 skill 目录复制或软链接到 Codex skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$(pwd)/fetch-linux-doc-patches" "${CODEX_HOME:-$HOME/.codex}/skills/fetch-linux-doc-patches"
```

安装后重启 Codex，使其重新发现 skill 元数据。

## 使用方法

抓取新的 linux-doc 补丁邮件，并在输出目录中保存增量状态：

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc
```

预览最近匹配到的邮件，不写入文件：

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output /tmp/linux-doc-preview \
  --since-days 1 \
  --no-state \
  --dry-run
```

抓取新补丁，并上传到默认 IMA 知识库 `linux-doc邮件列表`：

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc \
  --upload-to-ima
```

上传到指定的 IMA 知识库 ID：

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc \
  --upload-to-ima \
  --ima-kb-id "<knowledge_base_id>"
```

## 依赖要求

- Python 3.10 或更新版本。
- 能够访问 `nntp.lore.kernel.org` 的 `119` 端口；如果环境支持 TLS NNTP，
  也可以使用 `--tls --port 563` 访问 `563` 端口。
- 只有在使用 `--upload-to-ima` 时，才需要 Node.js 和已安装的 `ima-skill`。
- IMA 凭据可通过 `IMA_OPENAPI_CLIENTID` 和 `IMA_OPENAPI_APIKEY` 配置，
  也可以使用 `ima-skill` 支持的凭据文件。

## 输出文件

抓取脚本会写入：

- 按日期组织的目录，包含提取出的 `.patch` 文件。
- `manifest.jsonl`，每条已保存的补丁邮件对应一行记录。
- `.state.json`，用于保存 NNTP article 增量抓取状态。
- 启用 `--upload-to-ima` 时，会写入 `.ima-upload-state.json`。

生成的输出目录不应提交到本仓库。
