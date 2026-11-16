# GLM reasoning transport

JURE 的三个 JSON reasoning backends 现在可共同使用智谱官方 `glm-4.6v-flash`。模型名称对应用户指定的 4.6 Flash；官方标识带 `v`。

本模块只负责 HTTP、凭据、JSON 格式、调用预算和运行记录，不生成任何 case 的问题、假说、预测或工具顺序。模型在三个 Agent 各自的系统指令、context 和输出 schema 下工作。

配置见 [agent_runtime_glm46v_flash.json](../../configs/agent_runtime_glm46v_flash.json)。不切换其他模型或 endpoint；没有隐藏的 provider 重试。当前使用 `thinking=disabled`、temperature 0.2、最大输出 8192 tokens。`max_calls=80` 是单 transport 的技术上限，不表示已经运行或批准了 80 次调查调用。

```python
import getpass
from pathlib import Path
from jure.llm.glm import GLMConfig, GLMTransport, create_glm_backends

config = GLMConfig.model_validate_json(
    Path("configs/agent_runtime_glm46v_flash.json").read_text()
)
transport = GLMTransport(
    config=config,
    api_key=getpass.getpass("GLM API key: "),
    trace_dir="outputs/a_new_agent_run/model_calls",
)
backends = create_glm_backends(transport)
# Pass backends["explorer"], backends["investigator"], backends["critic"]
# into the existing JURE agents. Creating backends does not launch a case.
```

仅验证鉴权和 JSON 的 CLI，不读 CaseFile：

```bash
.venv/bin/python -m jure.llm.glm \
  --trace-dir outputs/a_new_glm_connection_check \
  --prompt-key
```

也可从 `JURE_GLM_API_KEY` 环境变量读取。密钥只进入 HTTP Authorization header，不进入模型 messages、代码、配置、日志或 CaseFile；交互输入不回显。本模块不持久化密钥。每次 trace 目录必须不存在，避免覆盖已有执行记录。

每次调用保存请求 body、原始 final response、JSON structured output（解析成功时）、模型身份、response ID、usage、耗时及失败状态；不保存 Authorization header 或模型 private reasoning 字段。只允许移除包裹整个返回值的 JSON code fence；不从杂文里挑 JSON，不补字段、不改科学内容。schema 和科学约束继续由原 Agent validators 负责。

macOS Python 缺少默认 CA bundle 时加载系统 `/etc/ssl/cert.pem`；TLS 证书和 hostname 校验保持开启，拒绝 HTTP 重定向以避免凭据转发。

2026-09-28 接入测试：已收到一次真实 `glm-4.6v-flash` 响应，内容为代码围栏包裹的 `{"ok": true}`，provider usage 为 95 input + 13 output = 108 tokens；该次原始 transport 因围栏报告格式失败，随后添加格式适配并通过测试。其余两次到达服务的请求返回 `429/1305`（模型当前访问量过大）；一次更早的请求止于本机 TLS。最后一次 live 验证仍为服务繁忙，不能标成完整 live smoke PASS。详见 `outputs/glm_provider_setup_20260928/SETUP_STATUS.json`。

现有证据工具仍是 Mock 实现；本次没有启动 Explorer、Investigator、Critic，没有将 Mock evidence 或手工分析写入真实 pilot。运行范围及真实 evidence adapters 应在下一次调查启动前明确。

来源：[GLM-4.6V-Flash 官方文档](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.6v-flash)。

```bash
.venv/bin/python -m pytest -q tests/test_glm_transport.py
```
