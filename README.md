# Embodied Navigation Agent

> 🤖 An embodied navigation system running on MacBook Pro M1 Pro + Habitat-Sim + OpenClaw
> Zero training, pure vision-driven, supports 5 navigation targets.

## Quick Start

```bash
# 1. Setup environment
bash scripts/setup_env.sh

# 2. Start Flask backend
python server/app.py

# 3. Open frontend
open frontend/index.html
```

## Architecture

```
User Input → OpenClaw (intent) → Skill → Flask Backend → Habitat-Sim + CLIP
                                                            ↓
                                                      MJPEG Stream → HTML Frontend
```

## Features

- ✅ Zero training — uses open-source pretrained models only
- ✅ Pure vision-driven — no privileged state information
- ✅ 5 navigation targets: sofa, bed, dining_table, desk, exit
- ✅ Real-time video streaming via MJPEG
- ✅ OpenClaw as high-level language brain
- ✅ Runs entirely on M1 Pro MacBook Pro

## Project Structure

```
embodied-nav/
├── docs/               # proposal.md, SPEC.md
├── modules/            # vision.py, navigator.py, agent.py
├── server/             # Flask backend + MJPEG
├── skills/             # OpenClaw Skill
├── frontend/           # HTML control panel
├── scripts/            # Setup + integration test
└── data/               # Replica scenes (download separately)
```

## Navigation Targets

| Command | Target |
|---------|--------|
| "请到沙发旁边" / "去沙发" | sofa |
| "我去睡觉" / "去床边" | bed |
| "去餐桌吃饭" | dining_table |
| "我要办公" / "去书桌" | desk |
| "带我出去" / "出门" | exit |

## Requirements

- macOS (Apple Silicon M1/M2/M3)
- Python 3.12 (via conda)
- ~5GB disk space for Replica dataset

## License

MIT