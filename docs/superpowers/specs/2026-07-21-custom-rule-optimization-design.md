# 本地 OpenClash 规则审核与优化设计

## 背景

本仓库在重新衔接上游历史后保留了 25 个本地提交。审核范围为 `upstream/main...HEAD` 中的自定义配置、规则文件和子模块指针。目标是在不改变既有分流意图的前提下，修复无效规则、消除策略冲突、降低明确的误匹配风险，并整理规则来源与策略组结构。

## 已确认的约束

- UK Wi-Fi Calling 和 PCDN 必须保留外部规则引用，以持续接收外部更新。
- 本地 UK 和 PCDN 规则继续作为补充层保留。
- 保留 `DOMAIN-KEYWORD` 规则类型，不做批量正则化或精确域名转换。
- `betboom` 只保留在代理规则中。
- 非标端口规则和策略组继续保持禁用。
- `google-cn` 继续经由谷歌服务策略，只修正与行为不符的注释。

## 规则来源设计

### UK Wi-Fi Calling

按以下顺序加载到 `🌎 UK-WiFi-Calling`：

1. 外部更新源：`https://raw.githubusercontent.com/iniwex5/tools/refs/heads/main/rules/UK-wifi-call.list`
2. 本地补充源：`https://raw.githubusercontent.com/WilliamLuuu/Custom_OpenClash_Rules/refs/heads/main/rule/UK-WiFi-Calling.list`

外部源由其维护者更新，本仓库不复制或改写外部内容。本地文件只保存需要固定保留或尚未进入外部源的补充规则。

### PCDN

现有 `iniwex5/tools` PCDN 地址返回 404，因此替换为可访问且使用 Clash classical 文本格式的外部源：

1. 外部更新源：`https://raw.githubusercontent.com/uselibrary/PCDN/main/pcdn.list`
2. 本地补充源：`https://raw.githubusercontent.com/WilliamLuuu/Custom_OpenClash_Rules/refs/heads/main/rule/PCDN.list`

两层规则均指向 `🌐 PCDN`，由该策略组统一执行 `REJECT`。

## 匹配规则优化

### 确定性修复

- 将 `cfg/Custom_Clash.ini` 第一行恢复为注释 `;Custom_OpenClash_Rules`。
- 将 `DOMAIN,38.59.246.49` 修正为 `IP-CIDR,38.59.246.49/32,no-resolve`。
- 将 Adobe 中混合了端口和两个主机名的无效规则拆分为合法的独立域名规则。
- 删除 `Betting-Direct.list` 中重复的 `csapi`。
- 从 `Betting-Direct.list` 删除 `betboom`，仅在 `Betting-Proxy.list` 保留。
- 删除未被引用且与 `VPN-Yuyujc.list` 内容相同的 `VPN-Yujc.list`。

### 明确的误匹配收紧

- 保留现有 `DOMAIN-KEYWORD` 规则，不批量改变匹配类型。
- 删除 `DOMAIN-KEYWORD,cloudfront`，避免所有使用 CloudFront 的无关域名被强制直连。
- Adobe 拒绝规则移除 `DOMAIN-SUFFIX,adobe.io` 和 `DOMAIN,www.adobe.com`，保留具体激活、许可、消息和遥测主机。
- 从本地 PCDN 规则删除与 PCDN 无明确关系的 `cdn.tools.unlayer.com`。
- 其他博彩关键词保持现状，避免在缺少完整观测域名时造成服务漏匹配。

## 策略组结构

- 新增 `🇬🇧 英国节点` 的 `url-test` 组，使用英国、UK、GB、London、Manchester 等节点名称特征进行匹配。
- 将 `🇬🇧 英国节点` 加入 `🚀 手动选择` 和 `🌎 UK-WiFi-Calling` 的可选项。
- `🌎 UK-WiFi-Calling` 仍包含手动选择、自动选择、全球直连及现有地区组，英国节点优先。
- `🌐 Adobe` 和 `🌐 PCDN` 保持独立的 `REJECT` 组。
- 所有 `ruleset` 目标必须存在对应的策略组；允许地区测速组仅作为其他策略组的候选项而不直接被规则引用。

## 子模块与文档

- 将 `overwrite/OpenClash_Overwrite` 恢复到 `upstream/main` 当前记录的提交，撤销本地对该子模块的历史回退。
- 更新 `rule/README.md`，列出新增的自定义规则文件、用途、策略方向和外部/本地来源关系。
- 删除文件时同步删除文档和配置引用，避免孤立规则。

## 自动验证

新增离线验证脚本与测试，至少检查：

- 支持的规则类型和字段数量。
- `DOMAIN`/`DOMAIN-SUFFIX` 值不是 IP、端口或包含空白的复合值。
- IP 使用合法 CIDR，并在需要时包含 `no-resolve`。
- 单个文件内不存在完全重复规则。
- 本地 DIRECT 与 PROXY 规则不存在完全相同的匹配项。
- 每个 `ruleset` 目标都有已定义策略组。
- 每个本地自定义规则文件都被配置引用或明确标为仅供维护。
- 配置文件不存在合并冲突标记和无效首行。

外部 URL 可用性作为独立的联网检查，不纳入必须离线通过的单元测试，避免网络波动导致本地验证不稳定。

## 验收标准

- 仓库现有 Python 单元测试全部通过。
- `generate_rules.py --check`、`generate_game_cdn.py --check` 和 `update_encrypted_dns.py --check` 全部通过。
- 新增的自定义规则验证全部通过。
- `git diff --check` 除明确保留的历史空白外无新增问题。
- UK 和 PCDN 外部 URL 在实施时可访问，格式可被 Subconverter 作为 classical ruleset 读取。
- `Custom_Clash.ini` 中没有未定义策略组，DIRECT/PROXY 不再包含相同的 `betboom` 规则。

## 非目标

- 不恢复非标端口分流。
- 不把全部 `DOMAIN-KEYWORD` 改成正则或精确域名。
- 不自动同步或重写第三方规则仓库。
- 不清理上游仓库中与本地自定义规则无关的代码。
