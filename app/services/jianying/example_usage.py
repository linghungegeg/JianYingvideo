from app.services.jianying_service import JianYingService


def main():
    svc = JianYingService()

    draft = svc.create_draft("demo", width=1080, height=1920, fps=30)
    if not draft.ok:
        print(draft.to_dict())
        return

    draft_id = draft.data["draft_id"]

    video_track = svc.create_track(draft_id, "video")
    text_track = svc.create_track(draft_id, "text")

    seg = svc.add_video_segment(
        draft_id,
        material="D:/materials/clip.mp4",
        target_timerange="0s-3s",
        track_name=video_track.data.get("track_name") if video_track.data else None,
    )
    print(seg.to_dict())

    txt = svc.add_text_segment(
        draft_id,
        text="Hello",
        timerange="0s-3s",
        track_name=text_track.data.get("track_name") if text_track.data else None,
    )
    print(txt.to_dict())

    anim = svc.add_text_animation(
        draft_id,
        text_segment_id=txt.data.get("text_segment_id"),
        animation_type="TextIntro",
        animation_name="弹跳",
    )
    print(anim.to_dict())

    export = svc.export_draft(draft_id, jianying_draft_path="D:/JianyingPro Drafts")
    print(export.to_dict())


if __name__ == "__main__":
    main()
