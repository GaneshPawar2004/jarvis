"""Skill registry. Every function returned here is exposed to the AI as a callable tool.

To add a new capability: write a typed function with a clear docstring in a skills
module, then add it to the right list below. Imports are inside the functions because the
laptop tools need Windows-only libraries that the cloud server doesn't have.
"""


def cloud_tools() -> list:
    """Tools that work anywhere, including the cloud server."""
    from skills import jobs, memory, system, web

    return [
        system.get_datetime,
        web.web_search,
        memory.remember,
        memory.forget,
        memory.recall_conversations,
        jobs.get_resume_profile,
        jobs.find_jobs,
        jobs.shortlist_job,
        jobs.list_jobs,
        jobs.update_job_status,
    ]


def local_tools() -> list:
    """Everything, for JARVIS running on the user's Windows laptop."""
    from skills import details, files, pc, phone, reminders, system, vision

    return cloud_tools() + [
        system.system_status,
        system.open_application,
        system.open_website,
        pc.set_volume,
        pc.change_volume,
        pc.mute_audio,
        pc.set_brightness,
        pc.change_brightness,
        pc.take_screenshot,
        pc.type_text,
        pc.press_keys,
        pc.media_control,
        files.find_files,
        files.open_file,
        reminders.set_reminder,
        reminders.list_reminders,
        reminders.cancel_reminder,
        vision.look_through_webcam,
        vision.look_at_screen,
        vision.remember_face,
        vision.forget_face,
        phone.phone_open_app,
        phone.phone_list_apps,
        phone.phone_read_screen,
        phone.phone_look_at_screen,
        phone.phone_tap,
        phone.phone_fill_field,
        phone.phone_type,
        phone.phone_press,
        phone.phone_scroll,
        phone.phone_status,
        details.vault_list_fields,
        details.vault_save_field,
    ]
