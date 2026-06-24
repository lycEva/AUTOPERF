# autoperf-cli

`autoperf-cli` 是面向 ARM64/AArch64 + 华为 Ascend 显卡环境的自动化性能测试工具，用于编排服务配置修改、Docker 容器重启、JMeter 压测、脚本监控和结果归档。

JMeter 只负责发起压测请求；CPU、内存、NPU 使用率和 NPU 显存占用由自定义 shell 脚本采集。

## 适用环境

- CPU：ARM64 / AArch64
- NPU：华为 Ascend 显卡
- 服务：Docker 容器
- 压测：Apache JMeter
- Python：3.8+

核心功能只依赖 Python 标准库。`matplotlib` 为可选依赖，仅用于额外生成 PNG 图表。

## 安装

```bash
python3 -m pip install -e .
chmod +x scripts/*.sh

autoperf --help
```

将用户级安装目录加入 `PATH`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

也可以在项目根目录直接使用模块方式运行：

```bash
python3 -m autoperf.cli --help
```

## 快速开始

完整压测示例：

```bash
autoperf run \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --service-workers 4 \
  --service-threads 8 \
  --threads 50 \
  --duration 600 \
  --output /root/test/results \
  --run-scripts /root/test/run_scripts \
  --interval 2 \
  --monitor-timeout 60 \
  --ready-log-pattern "Booting worker"
```

默认使用内置 JMX 模板 `templates/base.jmx`。运行时会复制模板到本次结果目录，只修改副本，不修改原始模板。

使用自定义 JMX：

```bash
autoperf run ... --jmx /path/to/custom.jmx
```

## 执行流程

`autoperf run` 会依次完成：

1. 修改本地 `server_config.json` 中的 `workers` 和 `threads`
2. `docker cp` 到容器内 `/hexapp/ai-<server_name>-serving/conf/server_config.json`
3. 重启容器并等待服务启动
4. 复制并修改 JMX 模板
5. 启动监控脚本和 JMeter 压测
6. 保存 JMeter、监控、日志和报告文件

`--ready-log-pattern` 用于指定服务启动成功的日志关键字。容器重启后，工具会轮询：

```bash
docker logs --tail 200 <container>
```

如果最近 200 行日志中出现指定文本，就开始压测。未设置该参数时，只检查容器运行状态和进程 PID。

## 常用命令

环境检查：

```bash
autoperf check \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --run-scripts scripts
```

只修改 JMX：

```bash
autoperf update-jmx \
  --jmx templates/base.jmx \
  --threads 100 \
  --duration 900
```

只修改并推送 `server_config.json`：

```bash
autoperf update-server-config \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --service-workers 4 \
  --service-threads 8 \
  --output /root/test/results \
  --restart
```

测试监控脚本：

```bash
autoperf test-monitor \
  --container ai-fs-serving \
  --workers 15 \
  --run-scripts scripts \
  --monitor-timeout 60
```

兼容旧脚本中的固定容器名：

```bash
autoperf update-scripts \
  --container ai-fs-serving \
  --run-scripts scripts
```

基于已有 `result.jtl` 补生成 JMeter 聚合报告：

```bash
autoperf aggregate-jtl --jtl /path/to/result.jtl
```

## 监控脚本

每次采样会并发调用 4 个脚本，并写入同一行 `monitor.csv`：

| 脚本 | 指标 | CSV 字段 | 单位 |
|---|---|---|---|
| `run_cpu.sh` | CPU 使用率 | `cpu_usage` | `%` |
| `run_mem.sh` | 内存占用 | `mem_usage` | GB |
| `run_npu_usage.sh` | NPU AICore 使用率 | `npu_usage` | `%` |
| `run_npu_mem.sh` | NPU 显存占用 | `npu_mem` | MiB |

采样间隔由 `--interval` 控制，默认 `0.1` 秒，最小有效值 `0.05` 秒。多 worker 场景建议使用 `2` 到 `5` 秒，避免监控本身影响被测服务。

脚本要求：

- 通过参数接收容器名，不写死容器名或 PID
- stdout 只输出一个数字
- 异常时输出 `0`
- CLI 调用时优先读取 `AUTOPERF_MONITOR_PIDS` 和 `AUTOPERF_MONITOR_RELATED_PIDS`

## 配置文件

当前版本只修改 `server_config.json` 中的 `workers` 和 `threads`，其他字段保持不变：

```json
{
  "use_gpu": true,
  "gpu_ids": "0",
  "gpu_mem": 20,
  "bind": "0.0.0.0:7000",
  "workers": 4,
  "threads": 8
}
```

容器内目标路径由 `--server-name` 决定：

```text
/hexapp/ai-<server_name>-serving/conf/server_config.json
```

例如 `--server-name fs` 对应：

```text
/hexapp/ai-fs-serving/conf/server_config.json
```

配置推送后必须重启容器。容器重启后，旧的 root PID 和子进程 PID 会失效，工具会重新获取。

## 输出结果

每次压测生成独立目录：

```text
<output>/<test_name>_<container>_<service_workers>w_<service_threads>t_<threads>jmx_<duration>s_<timestamp>/
```

主要文件：

```text
result.jtl
jmeter.log
run.log
config.json
<test_name>.modified.jmx
modified_server_config.json
jmeter_aggregate_report.html
jmeter_aggregate_report.csv
monitor/
  monitor.csv
  monitor_report.html
  cpu_usage.png
  mem_usage.png
  npu_usage.png
  npu_mem.png
scripts/
  run_cpu.sh
  run_mem.sh
  run_npu_usage.sh
  run_npu_mem.sh
```

`monitor_report.html` 为必产物，包含 CPU、内存、NPU 使用率和 NPU 显存曲线。安装 `matplotlib` 后会额外生成 PNG，PNG 生成失败不影响压测结果。

## 错误处理

以下关键步骤失败会终止压测：

- `server_config.json` 不存在、JSON 非法或缺少 `workers` / `threads`
- Docker、容器、容器内配置目录不可用
- `docker cp`、`docker restart` 或服务启动检查失败
- JMX 模板不存在、XML 解析失败或 JMeter 不存在

监控脚本单次失败不会终止压测，对应指标写入 `0` 并记录 warning。
