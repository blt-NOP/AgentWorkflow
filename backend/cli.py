"""不用启动网页或服务，直接执行同一个后端流程。"""
import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="会话名，例如 A、B")
    parser.add_argument("--message")
    parser.add_argument("--direction")
    parser.add_argument("--claim")
    parser.add_argument("--compute")
    parser.add_argument("--weeks", type=int)
    parser.add_argument("--dataset")
    parser.add_argument("--search", help="检索关键词；不提供时沿用已有材料")
    parser.add_argument("--model", action="store_true", help="真实调用 .env 配置的模型")
    parser.add_argument("--skill", help="提问策略 Skill 名称，默认 research-dialogue")
    parser.add_argument("--choice", help="回答上一轮选项，例如 compute-0")
    parser.add_argument("--show", action="store_true", help="只查看会话 JSON")
    parser.add_argument("--data-dir", help="可选：使用独立测试数据目录")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir
    from . import memory
    from .agent import run_turn
    if args.show:
        print(json.dumps(memory.load(args.session), ensure_ascii=False, indent=2))
        return
    if not args.message:
        parser.error("请提供 --message 或 --show")
    if args.weeks is not None and not 1 <= args.weeks <= 520:
        parser.error("--weeks 范围为1至520")
    facts = {key: getattr(args, key) for key in ("direction", "claim", "compute", "weeks", "dataset")
             if getattr(args, key) is not None}
    run_turn(args.session, args.message, facts, args.search, args.model, skill=args.skill, choice_id=args.choice)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"[失败] {type(error).__name__}: {error}")
        raise SystemExit(1)
