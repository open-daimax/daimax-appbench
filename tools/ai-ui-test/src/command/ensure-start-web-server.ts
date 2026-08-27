#!/usr/bin/env node
/**
 * ensure-start-web-server
 *
 * 说明：原实现依赖内部 npm registry 与内部技能包，开源版本已移除。
 * 本命令保留为无操作入口（no-op），避免外部脚本（run.sh）调用时报错。
 * 如需 start-web-server 能力，可自行集成任意 Web 开发服务器启动工具。
 */

console.log(
  '[ensure-start-web-server] This command is a no-op in the open-source release. ' +
    'The internal skill registry it previously used is not available. ' +
    'Please integrate any web dev server tooling of your choice.'
);
