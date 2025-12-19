# 后端系统增强功能

本文档描述了 WebWeaver 后端系统的增强功能，包括 StateBackend、CompositeBackend、工具结果自动卸载和 Prompt 缓存。

## 📋 目录

1. [StateBackend - 基于状态的临时存储](#statebackend)
2. [CompositeBackend - 路由多个后端](#compositebackend)
3. [工具结果自动卸载](#工具结果自动卸载)
4. [Prompt 缓存](#prompt-缓存)
5. [使用示例](#使用示例)

## StateBackend

`StateBackend` 是一个基于 LangGraph agent state 的临时存储后端。文件在对话线程内持久化，但不会跨线程保存。

### 特性

- **临时存储**: 文件存储在 agent state 中，随对话线程生命周期
- **自动检查点**: LangGraph 会在每个 agent 步骤后自动检查点状态
- **状态更新**: 操作返回 `files_update` 字典，用于更新 LangGraph state

### 使用示例

```python
from webweaver.backends import StateBackend
from langchain.tools import ToolRuntime

# 创建 StateBackend
runtime = ToolRuntime(state={"files": {}}, ...)
backend = StateBackend(runtime)

# 写入文件
result = backend.write("/test.txt", "Hello, World!")
if result.files_update:
    # 更新 state
    runtime.state["files"].update(result.files_update)

# 读取文件
content = backend.read("/test.txt")
```

## CompositeBackend

`CompositeBackend` 允许根据路径前缀将操作路由到不同的后端。这对于组合多个存储后端（如临时状态存储和持久存储）非常有用。

### 特性

- **路径路由**: 根据路径前缀自动路由到相应的后端
- **多后端支持**: 可以组合任意数量的后端
- **统一接口**: 提供统一的操作接口，隐藏后端复杂性

### 使用示例

```python
from webweaver.backends import StateBackend, FilesystemBackend, CompositeBackend
from langchain.tools import ToolRuntime

# 创建多个后端
runtime = ToolRuntime(state={"files": {}}, ...)
state_backend = StateBackend(runtime)
fs_backend = FilesystemBackend(root_dir="/data/memories")

# 创建组合后端
composite = CompositeBackend(
    default=state_backend,  # 默认后端
    routes={
        "/memories/": fs_backend,  # /memories/ 路径路由到文件系统后端
    }
)

# 使用组合后端
composite.write("/memories/notes.txt", "Important note")  # 写入文件系统
composite.write("/temp.txt", "Temporary")  # 写入状态后端
```

### 路由规则

- 路径前缀必须以 `/` 结尾（如 `/memories/`）
- 路由按长度排序（最长优先），确保精确匹配
- 根路径 `/` 会聚合所有后端的结果
- 不匹配任何路由的路径使用默认后端

## 工具结果自动卸载

`ToolResultEvictionMiddleware` 自动将过大的工具结果保存到文件系统，以管理 LLM 上下文窗口。

### 特性

- **自动检测**: 当工具结果超过阈值（默认 20k tokens，约 80k 字符）时自动触发
- **文件保存**: 将大结果保存到 `/large_tool_results/` 目录
- **智能提示**: 返回消息告知结果保存位置，并提供读取示例

### 配置

```python
from webweaver.middleware import ToolResultEvictionMiddleware
from webweaver.backends import FilesystemBackend

# 创建中间件
backend = FilesystemBackend(root_dir="/tmp/weaver")
eviction_middleware = ToolResultEvictionMiddleware(
    backend=backend,
    tool_token_limit_before_evict=20000,  # 20k tokens
)

# 处理工具结果
processed_content, files_update = eviction_middleware.process_tool_result(
    tool_call_id="call_123",
    result_content=large_result,
)
```

### 工作原理

1. 检查工具结果大小（字符数）
2. 如果超过阈值，保存到文件系统
3. 返回包含文件路径和内容预览的消息
4. Agent 可以使用 `read_file` 工具按需读取结果

## Prompt 缓存

Prompt 缓存中间件包装了 Anthropic 的 Prompt Caching 功能，可以缓存系统提示以减少成本。

### 特性

- **成本优化**: 缓存系统提示，减少重复 token 消耗
- **自动检测**: 仅在支持缓存的模型上生效
- **优雅降级**: 如果模型不支持缓存，可以忽略、警告或抛出异常

### 使用示例

```python
from webweaver.middleware.prompt_caching import create_prompt_caching_middleware

# 创建中间件（如果可用）
middleware = create_prompt_caching_middleware(
    unsupported_model_behavior="ignore"  # ignore, warn, or raise
)

if middleware:
    # 使用中间件
    pass
```

### 注意事项

- 需要安装 `langchain-anthropic` 包
- 仅对支持 prompt caching 的 Anthropic 模型有效
- 缓存的是系统提示，不是用户消息

## 使用示例

### 完整示例：组合多个后端和中间件

```python
from webweaver.backends import StateBackend, FilesystemBackend, CompositeBackend
from webweaver.middleware import ToolResultEvictionMiddleware
from webweaver.middleware.prompt_caching import create_prompt_caching_middleware
from langchain.tools import ToolRuntime

# 1. 设置后端
runtime = ToolRuntime(state={"files": {}}, ...)
state_backend = StateBackend(runtime)
persistent_backend = FilesystemBackend(root_dir="/data/persistent")
composite_backend = CompositeBackend(
    default=state_backend,
    routes={
        "/persistent/": persistent_backend,
    }
)

# 2. 设置工具结果卸载中间件
eviction_middleware = ToolResultEvictionMiddleware(
    backend=composite_backend,
    tool_token_limit_before_evict=20000,
)

# 3. 设置 Prompt 缓存（如果可用）
prompt_caching = create_prompt_caching_middleware()

# 4. 在 agent 中使用
# middleware_list = [eviction_middleware]
# if prompt_caching:
#     middleware_list.append(prompt_caching)
```

### 工具结果卸载集成

```python
from webweaver.tools.executor import ToolExecutor
from webweaver.middleware import ToolResultEvictionMiddleware

executor = ToolExecutor()
eviction = ToolResultEvictionMiddleware(backend=backend)

# 执行工具调用
results = executor.execute_tool_calls(agent_output)

# 处理结果（如果需要卸载）
for result in results:
    processed = eviction.intercept_tool_result(
        tool_name=result.tool_call.name,
        tool_call_id="call_123",
        result=result.result,
    )
```

## 实现细节

### 文件结构

```
src/webweaver/backends/
├── __init__.py          # 导出所有后端
├── protocol.py          # 后端协议定义
├── filesystem.py        # 文件系统后端
├── state.py             # 状态后端
├── composite.py         # 组合后端
└── utils.py             # 后端工具函数

src/webweaver/middleware/
├── tool_result_eviction.py  # 工具结果卸载中间件
└── prompt_caching.py        # Prompt 缓存包装器
```

### 依赖项

- `langchain`: 用于 ToolRuntime 和 agent state
- `langchain-anthropic` (可选): 用于 Prompt Caching
- `wcmatch` (可选): 用于高级 glob 匹配

## 最佳实践

1. **选择合适的后端**: 
   - 临时数据使用 `StateBackend`
   - 持久数据使用 `FilesystemBackend`
   - 混合场景使用 `CompositeBackend`

2. **工具结果卸载**:
   - 设置合理的 token 限制（默认 20k）
   - 确保后端有足够的存储空间
   - 监控卸载频率，调整阈值

3. **Prompt 缓存**:
   - 仅在 Anthropic 模型上使用
   - 系统提示应该相对稳定以最大化缓存效果
   - 监控 token 使用量以验证缓存效果

## 未来改进

### 存储后端扩展
- [ ] 支持异步操作（async/await API）
- [ ] StoreBackend - 基于 LangGraph Store 的持久化存储后端
- [ ] 更多存储后端（S3, Redis, MongoDB, PostgreSQL 等）
- [ ] 云存储集成（AWS S3, Azure Blob, Google Cloud Storage）
- [ ] 内存缓存后端（用于高频访问的临时数据）

### 文件管理增强
- [ ] 文件版本控制和历史记录
- [ ] 文件元数据支持（标签、分类、自定义属性）
- [ ] 文件权限管理（读写权限、访问控制）
- [ ] 文件锁定机制（防止并发修改冲突）
- [ ] 文件快照功能（时间点恢复）
- [ ] 文件差异比较和合并
- [ ] 文件模板系统（预定义模板快速创建）

### 性能和优化
- [ ] 后端性能监控和指标收集
- [ ] 后端缓存层（LRU、TTL 缓存策略）
- [ ] 批量操作优化（批量读写、事务支持）
- [ ] 文件压缩选项（gzip、brotli 压缩）
- [ ] 增量同步和差异传输
- [ ] 文件分片和流式处理（大文件处理）

### 搜索和索引
- [ ] 全文搜索功能（Elasticsearch、Meilisearch 集成）
- [ ] 文件内容索引和快速检索
- [ ] 智能文件推荐（基于使用模式）
- [ ] 文件依赖关系追踪
- [ ] 文件标签和分类系统

### 安全和审计
- [ ] 文件访问审计日志
- [ ] 文件加密支持（端到端加密）
- [ ] 文件完整性校验（哈希验证）
- [ ] 文件大小限制和配额管理
- [ ] 文件访问频率限制（防止滥用）

### 自动化和策略
- [ ] 文件自动清理策略（基于时间、大小、访问频率）
- [ ] 文件自动备份和恢复
- [ ] 文件迁移工具（后端间迁移）
- [ ] 文件变更通知系统（事件驱动）
- [ ] 文件生命周期管理（自动归档、删除）

### 协作和共享
- [ ] 文件共享和协作功能
- [ ] 文件评论和标注
- [ ] 文件变更通知（实时更新）
- [ ] 文件冲突解决机制

### 监控和诊断
- [ ] 后端健康检查
- [ ] 性能分析和瓶颈识别
- [ ] 存储使用情况统计
- [ ] 错误追踪和报告

