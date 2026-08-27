# MCP 工具服务接入指南

MCP (Model Context Protocol) 允许 EvalApp 评测框架连接外部工具服务，扩展评测的能力边界。通过 MCP，评测可以调用文件系统、数据库、API 网关等外部服务。

## 前置条件

- MCP 兼容的服务端（本地或远程）
- `evalapp.yaml` 配置文件

## 配置接入

### 1. 启用 MCP

在 `evalapp.yaml` 中配置：

```yaml
mcp:
  enabled: true
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@anthropic/mcp-server-filesystem", "/tmp/workspace"]
```

### 2. 服务端配置

MCP 支持两种接入方式：

**本地命令启动**（推荐开发环境）：

```yaml
mcp:
  enabled: true
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@anthropic/mcp-server-filesystem", "/data"]
      env:
        NODE_ENV: production
```

**远程 URL 连接**（推荐生产环境）：

```yaml
mcp:
  enabled: true
  servers:
    - name: remote-tools
      url: http://mcp-server.example.com/mcp
```

## 配置字段参考

```yaml
mcp:
  enabled: false          # 是否启用 MCP 工具服务（bool，默认 false）
  servers: []             # MCP 服务端列表
```

单个服务端配置：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 服务名称标识，如 "filesystem" |
| `command` | string | 二选一 | 本地启动命令（与 `url` 互斥） |
| `args` | list | 否 | 启动命令参数列表 |
| `env` | dict | 否 | 传递给服务进程的环境变量 |
| `url` | string | 二选一 | 远程 MCP 服务 URL（与 `command` 互斥） |

## 生命周期

MCP 服务随评测进程管理：
- **启动**：评测开始时按配置顺序依次启动本地服务 / 连接远程服务
- **健康检查**：启动后等待服务就绪（默认 10s 超时）
- **调用**：评测工具通过 MCP 协议调用已注册的服务能力
- **关闭**：评测结束时自动终止本地服务进程

## 常见服务端

| 服务 | 用途 | 安装命令 |
|------|------|---------|
| `@anthropic/mcp-server-filesystem` | 文件系统访问 | `npx -y @anthropic/mcp-server-filesystem` |
| `@anthropic/mcp-server-github` | GitHub API | `npx -y @anthropic/mcp-server-github` |
| 自定义服务 | 业务定制 | 实现 MCP Server 协议即可 |

## 错误处理

- **服务启动失败**：日志输出 `[mcp] Failed to start server: {name}`，跳过该服务继续评测
- **连接超时**：默认 10s，超时后标记服务不可用
- **调用失败**：工具层捕获异常，回退到内置实现

## 常见问题

**Q: 不配置 MCP 会影响评测吗？**

不会。MCP 是可选扩展，所有核心评测功能均可通过内置工具完成。

**Q: 如何调试 MCP 服务？**

设置环境变量 `DEBUG=mcp:*` 可查看 MCP 协议通信日志。

**Q: command 和 url 可以同时配置吗？**

不可以，二者互斥。本地开发推荐 `command`，生产环境推荐 `url`。
