# 闲鱼搜索 MCP 服务

把 Unraid 上的 `ai-goofish-monitor` 包装成 4 个 MCP 工具，供 DeepSeek Harness
（或任意 MCP 客户端）调用。**只做 HTTP 转发**，搜索本身在服务端后台跑，
不会让调用方挂着等。

## 运行要求

- Python 3.10+，只用标准库，无需 `pip install`
- 能访问 `http://192.168.70.138:8013`（默认值，可用环境变量覆盖）

```bash
XIANYU_BASE_URL=http://192.168.70.138:8013 python3 mcp_server/xianyu_search_server.py
```

## 工具

| 工具 | 作用 |
| --- | --- |
| `search_submit` | 提交搜索（`keyword`、`max_pages`、价格区间、地区、个人卖家），立即返回 `job_id` |
| `search_status` | 查状态 + 已抓条数 + 日志尾部 |
| `search_results` | 分页取结果（标题、价格、地区、链接、解析出的 chip/内存/存储） |
| `search_cancel` | 取消排队或运行中的任务 |

典型流程：`search_submit` → 回一句“已排队” → 1–3 分钟后 `search_status`
→ 完成后再 `search_results` 并总结。一次深搜通常几分钟到几十分钟。

## DSH 接入

在 `~/.dsh/profiles/desktop/cordis.patch.yml` 末尾追加：

```yaml
- insert:
    - id: xianyu-search
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: xianyu
        transport: stdio
        command: /opt/homebrew/bin/python3
        args:
          - /Users/wangyichuan/selfapp/ai-goofish-monitor/mcp_server/xianyu_search_server.py
        env:
          XIANYU_BASE_URL: http://192.168.70.138:8013
        toolCallTimeoutMs: 120000
        failOnStartupError: false
```

工具会以 `mcp__xianyu__search_submit` 这样的名字出现。改完需要重载/重启
DSH Host 才会生效。

## 注意

- 服务端 API 目前没有鉴权，仅适合内网使用；不要把 8013 暴露到公网。
- 搜索任务和定时任务共享同一个闲鱼登录态与浏览器，服务端保证同一时间只跑一个；
  定时任务若正好撞上会跳过本轮。
- 结果只写到 `data/search_jobs/<job_id>/`，不进任务列表、不写行情快照。
