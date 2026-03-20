# -*- coding: utf-8 -*-
"""
Author: jian wei
File Name:debug.py
"""
from app.utils.jianying_mcp.jianying.draft import Draft
from app.utils.jianying_mcp.jianying.track import Track
from app.utils.jianying_mcp.jianying.audio import AudioSegment
from app.utils.jianying_mcp.jianying.text import TextSegment
from app.utils.jianying_mcp.jianying.export import ExportDraft
from app.utils.jianying_mcp.jianying.video import VideoSegment


def main():
    draft = Draft()
    draft_id = draft.create_draft(draft_name="test")["draft_id"]
    print(draft_id)
    Track(draft_id).add_track(track_type="text", track_name="text")
    Track(draft_id).add_track(track_type="video", track_name="video")
    Track(draft_id).add_track(track_type="audio", track_name="audio")

    audio_segment = AudioSegment(draft_id, track_name="audio")
    audio_segment.add_audio_segment(material="../material/audio.MP3", target_timerange="0s-16s")
    audio_segment.add_fade("1s", "0.5s")

    video_segment1 = VideoSegment(draft_id, track_name="video")
    video_segment1.add_video_segment(material="../material/video1.mp4", target_timerange="0s-6s")
    video_segment1.add_transition("叠化", "1s")
    video_segment1.add_filter("冷淡", intensity=50.0)
    video_segment2 = VideoSegment(draft_id, track_name="video")
    video_segment2.add_video_segment(material="../material/video2.mp4", target_timerange="6s-5s")
    video_segment2.add_background_filling("blur", blur=0.5)
    video_segment2.add_mask(
        mask_type="圆形",
        mask_radius=0.5,
        mask_center=[0.5, 0.5],
        mask_rotate=0.0,
        mask_aspect=1.0,
    )

    text_segment = TextSegment(draft_id, track_name="text")
    text_segment.add_text_segment(
        text="Hello World",
        font_size=40,
        target_timerange="0s-6s",
    )

    export = ExportDraft()
    export.export_draft(draft_id, draft_name="test", export_zip=False)


if __name__ == "__main__":
    main()
