"""
CandidateManager — 管理资产候选项（抽卡/选择）

每个资产（角色图、场景图、首帧图、视频、TTS）可有多个候选项，
用户可以预览、抽卡（生成新候选）、选择最佳候选。

数据持久化在 {output_dir}/candidates.json
"""

import json
import os
import time
import glob as glob_mod
from typing import Optional


class CandidateManager:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.path = os.path.join(output_dir, "candidates.json")
        self._data = None

    def load(self) -> dict:
        if self._data is not None:
            return self._data
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._data = json.load(f)
        else:
            self._data = {"version": 1, "assets": {}, "invalidated": []}
        return self._data

    def save(self):
        data = self.load()
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def register(self, asset_key: str, path: str) -> int:
        """注册新候选项，返回版本号。"""
        data = self.load()
        assets = data.setdefault("assets", {})
        entry = assets.setdefault(asset_key, {"candidates": [], "selected": 0})

        version = len(entry["candidates"]) + 1
        entry["candidates"].append({
            "version": version,
            "path": path,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 自动选择最新的
        entry["selected"] = version
        self.save()
        return version

    def get_selected_path(self, asset_key: str) -> Optional[str]:
        """返回当前选中候选项的绝对路径。"""
        data = self.load()
        entry = data.get("assets", {}).get(asset_key)
        if not entry or not entry.get("candidates"):
            return None
        selected = entry.get("selected", 1)
        for c in entry["candidates"]:
            if c["version"] == selected:
                p = c["path"]
                if not os.path.isabs(p):
                    p = os.path.join(self.output_dir, p)
                return p
        return None

    def select(self, asset_key: str, version: int) -> bool:
        """选择指定版本的候选项。"""
        data = self.load()
        entry = data.get("assets", {}).get(asset_key)
        if not entry:
            return False
        versions = [c["version"] for c in entry["candidates"]]
        if version not in versions:
            return False
        entry["selected"] = version
        self.save()
        return True

    def next_version(self, asset_key: str) -> int:
        """返回下一个版本号。"""
        data = self.load()
        entry = data.get("assets", {}).get(asset_key, {"candidates": []})
        return len(entry.get("candidates", [])) + 1

    def list_candidates(self, asset_key: str) -> list[dict]:
        """列出指定资产的所有候选项。"""
        data = self.load()
        entry = data.get("assets", {}).get(asset_key)
        if not entry:
            return []
        selected = entry.get("selected", 0)
        result = []
        for c in entry["candidates"]:
            p = c["path"]
            if not os.path.isabs(p):
                p = os.path.join(self.output_dir, p)
            result.append({
                **c,
                "abs_path": p,
                "exists": os.path.exists(p),
                "is_selected": c["version"] == selected,
            })
        return result

    def get_all_for_type(self, asset_type: str) -> dict:
        """返回某类型的所有资产条目（如 char_ref, video, tts）。"""
        data = self.load()
        return {
            k: v for k, v in data.get("assets", {}).items()
            if k.startswith(f"{asset_type}:")
        }

    def invalidate(self, asset_key: str):
        """标记资产为失效，下次 run 时会重新生成。"""
        data = self.load()
        inv = data.setdefault("invalidated", [])
        if asset_key not in inv:
            inv.append(asset_key)
        self.save()

    def is_invalidated(self, asset_key: str) -> bool:
        data = self.load()
        return asset_key in data.get("invalidated", [])

    def clear_invalidation(self, asset_key: str):
        data = self.load()
        inv = data.get("invalidated", [])
        if asset_key in inv:
            inv.remove(asset_key)
            self.save()

    def invalidate_cascade(self, edit_type: str, seg_num: int = None,
                           sub_idx: int = None, char_id: str = None,
                           scene_id: str = None, storyboard: dict = None):
        """根据编辑类型级联失效下游资产。"""
        if edit_type == "narration_text" and seg_num:
            self.invalidate(f"tts:{seg_num}")
            # 失效该段所有视频
            self._invalidate_segment_videos(seg_num, storyboard)

        elif edit_type == "emotion" and seg_num:
            self.invalidate(f"tts:{seg_num}")

        elif edit_type == "image_prompt" and seg_num:
            self.invalidate(f"first_frame:seg{seg_num:02d}_sub01")

        elif edit_type == "video_prompt" and seg_num and sub_idx is not None:
            self.invalidate(f"video:seg{seg_num:02d}_sub{sub_idx+1:02d}")

        elif edit_type == "appearance_prompt" and char_id:
            self.invalidate(f"char_ref:{char_id}")
            self._invalidate_char_videos(char_id, storyboard)

        elif edit_type == "scene_prompt" and scene_id:
            self.invalidate(f"scene_bg:{scene_id}")

        elif edit_type == "select_char_ref" and char_id:
            self._invalidate_char_videos(char_id, storyboard)

        elif edit_type == "select_first_frame" and seg_num and sub_idx is not None:
            self.invalidate(f"video:seg{seg_num:02d}_sub{sub_idx+1:02d}")

    def _invalidate_segment_videos(self, seg_num, storyboard):
        if not storyboard:
            return
        for seg in storyboard.get("segments", []):
            if seg.get("segment_number") == seg_num:
                for si in range(len(seg.get("sub_shots", []))):
                    self.invalidate(f"video:seg{seg_num:02d}_sub{si+1:02d}")

    def _invalidate_char_videos(self, char_id, storyboard):
        if not storyboard:
            return
        for seg in storyboard.get("segments", []):
            if char_id in seg.get("characters_in_shot", []):
                sn = seg["segment_number"]
                for si in range(len(seg.get("sub_shots", []))):
                    self.invalidate(f"video:seg{sn:02d}_sub{si+1:02d}")

    def migrate_from_existing(self, output_dir: str):
        """从旧目录（无 candidates.json）迁移，扫描已有文件自动注册。"""
        data = self.load()
        if data.get("assets"):
            return  # 已有数据，不迁移

        # 扫描角色图
        for f in sorted(glob_mod.glob(f"{output_dir}/characters/charref_*.*")):
            basename = os.path.basename(f)
            # 提取 char_id: charref_char_001_0.png → char_001
            parts = basename.replace("charref_", "").split("_")
            if len(parts) >= 2:
                cid = f"{parts[0]}_{parts[1]}"
                key = f"char_ref:{cid}"
                if key not in data.get("assets", {}):
                    self.register(key, os.path.relpath(f, output_dir))

        # 扫描场景图
        for f in sorted(glob_mod.glob(f"{output_dir}/scenes/scenebg_*.*")):
            basename = os.path.basename(f)
            parts = basename.replace("scenebg_", "").split("_")
            if len(parts) >= 2:
                sid = f"{parts[0]}_{parts[1]}"
                key = f"scene_bg:{sid}"
                if key not in data.get("assets", {}):
                    self.register(key, os.path.relpath(f, output_dir))

        # 扫描首帧图
        for f in sorted(glob_mod.glob(f"{output_dir}/images/seg*_sub*.*")):
            basename = os.path.basename(f).split(".")[0]
            if "_fb" in basename or "_v" in basename:
                continue
            key = f"first_frame:{basename.split('_0')[0]}"
            if key not in data.get("assets", {}):
                self.register(key, os.path.relpath(f, output_dir))

        # 扫描视频
        for f in sorted(glob_mod.glob(f"{output_dir}/videos/seg*_sub*.mp4")):
            basename = os.path.basename(f).replace(".mp4", "")
            if "_v" in basename:
                continue
            key = f"video:{basename}"
            if key not in data.get("assets", {}):
                self.register(key, os.path.relpath(f, output_dir))

        # 扫描 TTS
        for f in sorted(glob_mod.glob(f"{output_dir}/audio/seg_*.mp3")):
            basename = os.path.basename(f)
            # seg_01.mp3 → 1
            num = int(basename.replace("seg_", "").replace(".mp3", ""))
            key = f"tts:{num}"
            if key not in data.get("assets", {}):
                self.register(key, os.path.relpath(f, output_dir))
