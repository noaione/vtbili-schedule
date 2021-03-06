import asyncio
import logging
from datetime import datetime, timezone

from utils import TwitchHelix, VTBiliDatabase

vtlog = logging.getLogger("jobs.twitch")


async def find_channel_id(user_id: str, dataset: list):
    for data in dataset:
        if data["user_id"] == user_id:
            return data["id"]


async def twitch_channels(DatabaseConn: VTBiliDatabase, TwitchConn: TwitchHelix, twitch_dataset: list):
    twitch_usernames = [user["id"] for user in twitch_dataset]
    vtlog.info("Fetching Twitch API...")
    twitch_results = await TwitchConn.fetch_channels(twitch_usernames)

    vtlog.info("Parsing results...")
    for result in twitch_results:
        vtlog.info(f"|-- Parsing: {result['login']}")
        vtlog.info(f"|-- Fetching followers: {result['login']}")
        followers_data = await TwitchConn.fetch_followers(result["id"])

        chan_id = result["login"]

        data = {
            "id": chan_id,
            "user_id": result["id"],
            "name": result["display_name"],
            "description": result["description"],
            "thumbnail": result["profile_image_url"],
            "followerCount": followers_data["total"],
            "viewCount": result["view_count"],
            "platform": "twitch",
        }

        vtlog.info(f"Updating channels database for {chan_id}...")
        try:
            await asyncio.wait_for(DatabaseConn.update_data("twitch_channels", {chan_id: data}), 15.0)
        except asyncio.TimeoutError:
            await DatabaseConn.release()
            DatabaseConn.raise_error()
            vtlog.error("Failed to update twitch channels data, timeout by 15s...")


async def twitch_heartbeat(DatabaseConn: VTBiliDatabase, TwitchConn: TwitchHelix, twitch_dataset: list):
    twitch_usernames = [user["id"] for user in twitch_dataset]
    vtlog.info("Fetching Twitch API...")
    twitch_results = await TwitchConn.fetch_live_data(twitch_usernames)

    if not twitch_results:
        vtlog.warn("No one is live right now, bailing...")
        await DatabaseConn.update_data("twitch_data", {"live": []})
        return 1

    vtlog.info("Parsing results...")
    lives_data = []
    for result in twitch_results:
        if "type" in result and result["type"] == "":
            vtlog.warn(f"|= Skipping: {result['user_id']}")
            continue
        start_time = result["started_at"]

        login_name = await find_channel_id(result["user_id"], twitch_dataset)
        vtlog.info(f"|= Processing: {login_name}")

        thumbnail = result["thumbnail_url"]
        try:
            thumbnail = thumbnail.format(width="1280", height="720")
        except KeyError:
            pass

        start_utc = (
            datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        )

        data = {
            "id": result["id"],
            "title": result["title"],
            "startTime": start_utc,
            "channel": login_name,
            "channel_id": result["user_id"],
            "thumbnail": thumbnail,
            "platform": "twitch",
        }
        lives_data.append(data)

    if lives_data:
        lives_data.sort(key=lambda x: x["startTime"])

    upd_data = {"live": lives_data}
    vtlog.info("Updating database...")
    try:
        await asyncio.wait_for(DatabaseConn.update_data("twitch_data", upd_data), 15.0)
    except asyncio.TimeoutError:
        await DatabaseConn.release()
        DatabaseConn.raise_error()
        vtlog.error("Failed to update twitch live data, timeout by 15s...")
