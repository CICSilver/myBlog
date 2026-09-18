from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from app.database import BodyMetric, DatabaseHelper, Blog, Diary, Workout, normalize_cover_url
from app.fitness_activity import (
    build_activity_calendar as build_fitness_calendar,
    build_chart,
    build_month_calendar as build_fitness_month,
    build_year_overview as build_fitness_year,
    activity_summary as fitness_summary,
    month_summary,
)
from app.fitness_model import (
    DAY_TYPES,
    MOVEMENTS,
    balance,
    exercise_totals,
    movement_kind,
    records,
    volume_by_day,
    weight_options,
    workout_totals,
)
from app.auth import admin_logout, current_admin_authenticated, login_required, validate_csrf_token
from app.diary_policy import diary_date, location_needs_retry, better_location
from app.diary_metadata import fetch_diary_metadata
from app.diary_activity import (
    activity_summary,
    build_activity_calendar,
    build_month_calendar,
    build_year_overview,
    diary_activity_counts,
    word_milestone,
    year_char_total,
)
from app.view_filter import (
    EFFECTIVE_VIEW_SECONDS,
    READING_HEARTBEAT_SECONDS,
    is_crawler_user_agent,
    is_effective_reading_seconds,
    is_loopback_ip,
    is_verified_crawler_ip,
    normalize_reading_seconds,
)
from datetime import date, datetime, timedelta
import json
import math
import os
import re
import secrets
from zoneinfo import ZoneInfo

main = Blueprint('main', __name__)
dbHelper = DatabaseHelper()
SITE_NAME = "Silver's Blog"
PERSONAL_INTRO = "人事匆匆，或许有些可以留在这里。"
SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".webp": "webp",
}
DIARY_WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
# ========================= 辅助函数 =========================
def get_site_context():
    return {
        "site_name": SITE_NAME,
        "personal_intro": PERSONAL_INTRO,
    }

def init_index_with_blogs(_blogs):
    categories = dbHelper.get_all_categories()
    dateList = dbHelper.get_all_date()
    return render_template(
        'index.html',
        blogs=_blogs,
        categories=categories,
        dateList=dateList,
        **get_site_context(),
    )

def _image_upload_error(message, status_code=400):
    return jsonify({"status": "error", "message": message}), status_code


def _detect_image_type(payload):
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"

    return None


def _allowed_image_extension(filename):
    _, extension = os.path.splitext(filename or "")
    return SUPPORTED_IMAGE_EXTENSIONS.get(extension.lower())


def _image_size_message(image_label, max_bytes):
    return "{0}不能超过 {1}MB。".format(image_label, max_bytes // (1024 * 1024))


def _store_uploaded_image(uploaded_file, upload_dir, max_bytes, image_label):
    if uploaded_file is None:
        return None, _image_upload_error("请选择要上传的{0}。".format(image_label))

    expected_type = _allowed_image_extension(uploaded_file.filename)
    if expected_type is None:
        return None, _image_upload_error("{0}仅支持 JPG、PNG 或 WebP。".format(image_label))

    payload = uploaded_file.stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        return None, _image_upload_error(_image_size_message(image_label, max_bytes), 413)

    if not payload:
        return None, _image_upload_error("{0}不能为空。".format(image_label))

    detected_type = _detect_image_type(payload)
    if detected_type is None:
        return None, _image_upload_error("{0}格式无法识别。".format(image_label))

    if detected_type != expected_type:
        return None, _image_upload_error("{0}扩展名与实际格式不一致。".format(image_label))

    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    filename = "{0}.{1}".format(secrets.token_urlsafe(16), detected_type)
    relative_path = os.path.join(year, month, filename)
    target_path = os.path.join(upload_dir, relative_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    with open(target_path, "wb") as image_file:
        image_file.write(payload)

    return "/".join((year, month, filename)), None


def _parse_diary_coordinates(latitude, longitude, accuracy):
    latitude = "" if latitude is None else str(latitude).strip()
    longitude = "" if longitude is None else str(longitude).strip()
    accuracy = "" if accuracy is None else str(accuracy).strip()

    if not latitude and not longitude and not accuracy:
        return None

    if not latitude or not longitude:
        raise ValueError("定位坐标不完整。")

    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
        accuracy_value = float(accuracy) if accuracy else None
    except ValueError:
        raise ValueError("定位坐标格式无效。")

    numeric_values = [latitude_value, longitude_value]
    if accuracy_value is not None:
        numeric_values.append(accuracy_value)
    if not all(math.isfinite(value) for value in numeric_values):
        raise ValueError("定位坐标必须是有限数字。")
    if not -90 <= latitude_value <= 90 or not -180 <= longitude_value <= 180:
        raise ValueError("定位坐标超出有效范围。")
    if accuracy_value is not None and accuracy_value < 0:
        raise ValueError("定位精度不能小于零。")

    return latitude_value, longitude_value, accuracy_value


# =========================== 路由 ===========================
@main.route('/')
def index():
    return init_index_with_blogs(dbHelper.get_recent_blogs())

@main.route('/media/covers/<path:filename>')
def media_cover(filename):
    return send_from_directory(current_app.config["BLOG_COVER_UPLOAD_DIR"], filename)


@main.route('/media/articles/<path:filename>')
def media_article_image(filename):
    return send_from_directory(current_app.config["BLOG_ARTICLE_IMAGE_UPLOAD_DIR"], filename)


@main.route('/media/diaries/<path:filename>')
@login_required
def media_diary_image(filename):
    return send_from_directory(current_app.config["BLOG_DIARY_IMAGE_UPLOAD_DIR"], filename)


@main.route('/diary', methods=['GET'])
@login_required
def diary():
    timezone = ZoneInfo(current_app.config["BLOG_TIMEZONE"])
    now = datetime.now(timezone)
    today = diary_date(now)
    today_date = today.isoformat()

    month_value = request.args.get("month", today.strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month_value):
        abort(400)

    archive_year = int(month_value[:4])
    archive_month = int(month_value[5:])
    try:
        datetime(archive_year, archive_month, 1)
    except ValueError:
        abort(400)
    if (archive_year, archive_month) > (today.year, today.month):
        abort(400)

    diaries = dbHelper.get_diaries_by_month(str(archive_year), archive_month)
    for diary_entry in diaries:
        diary_entry.weekday_label = DIARY_WEEKDAY_LABELS[
            datetime.strptime(diary_entry.entry_date, "%Y-%m-%d").weekday()
        ]

    is_current_month = (archive_year, archive_month) == (today.year, today.month)
    today_diary = dbHelper.get_diary_by_date(today_date) if is_current_month else None
    activity_counts = diary_activity_counts(dbHelper.get_all_diaries(), today)
    month_calendar = build_month_calendar(activity_counts, archive_year, archive_month, today)
    for week in month_calendar["weeks"]:
        for day in week["days"]:
            if day and day["count"]:
                day["url"] = _diary_detail_url(day["date"])
    first_of_month = date(archive_year, archive_month, 1)
    previous_month = first_of_month - timedelta(days=1) if first_of_month > date.min else None
    next_month = (first_of_month + timedelta(days=32)).replace(day=1)

    return render_template(
        'diary.html',
        diaries=diaries,
        today_diary=today_diary,
        retry_location=location_needs_retry(today_diary.location if today_diary else {}),
        today_date=today_date,
        today_weekday=DIARY_WEEKDAY_LABELS[today.weekday()],
        is_current_month=is_current_month,
        archive_year=archive_year,
        archive_month=archive_month,
        archive_count=len(diaries),
        month_value=month_value,
        activity=activity_summary(activity_counts, archive_year, today),
        month_calendar=month_calendar,
        year_overview=build_year_overview(activity_counts, archive_year, today),
        milestone=word_milestone(year_char_total(activity_counts, archive_year)),
        previous_month_value=previous_month.strftime("%Y-%m") if previous_month else None,
        next_month_value=None if is_current_month else next_month.strftime("%Y-%m"),
        today_month=today.strftime("%Y-%m"),
        **get_site_context(),
    )


def _diary_detail_url(entry_date):
    year, month, day = map(int, entry_date.split("-"))
    return url_for("main.diary_detail", year=year, month=month, day=day)


@main.route('/diary/activity', methods=['GET'])
@login_required
def diary_activity():
    today = diary_date(datetime.now(ZoneInfo(current_app.config["BLOG_TIMEZONE"])))
    year_value = request.args.get("year", str(today.year))
    if not re.fullmatch(r"[0-9]{1,4}", year_value) or not 1 <= int(year_value) <= today.year:
        return jsonify({"message": "请选择有效年份。"}), 400
    counts = diary_activity_counts(dbHelper.get_all_diaries(), today)
    calendar = build_activity_calendar(counts, int(year_value), today)
    for day in calendar["days"]:
        if day is not None:
            day["url"] = _diary_detail_url(day["date"]) if day["count"] else None
    response = jsonify(calendar)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@main.route('/diary', methods=['POST'])
@login_required
def save_diary():
    validate_csrf_token()

    content = request.form.get("content", "")
    if not content.strip():
        return jsonify({"status": "error", "message": "日记正文不能为空。"}), 400

    uploaded_files = [
        uploaded_file
        for uploaded_file in request.files.getlist("diary-image")
        if uploaded_file is not None and uploaded_file.filename
    ]
    if len(uploaded_files) > 1:
        return _image_upload_error("日记仅支持上传一张图片。")

    timezone = ZoneInfo(current_app.config["BLOG_TIMEZONE"])
    now = datetime.now(timezone)
    today = diary_date(now)
    today_date = today.isoformat()
    if request.form.get("entry_date") not in (None, "", today_date):
        return jsonify({"status": "error", "message": "已超过这篇日记的可编辑时间，请刷新页面后记录新一天。"}), 409
    existing_diary = dbHelper.get_diary_by_date(today_date)
    old_location = existing_diary.location if existing_diary else {}
    old_weather = existing_diary.weather if existing_diary else {}

    try:
        submitted_coordinates = _parse_diary_coordinates(
            request.form.get("latitude"),
            request.form.get("longitude"),
            request.form.get("accuracy"),
        )

        stored_coordinates = None
        if (
            old_location.get("latitude") not in (None, "")
            and old_location.get("longitude") not in (None, "")
        ):
            stored_coordinates = _parse_diary_coordinates(
                old_location.get("latitude"),
                old_location.get("longitude"),
                old_location.get("accuracy_m"),
            )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    location_needs_metadata = (
        not old_location
        or old_location.get("formatted_address") in (None, "")
    )
    weather_needs_metadata = (
        not old_weather
        or old_weather.get("condition") in (None, "")
        or old_weather.get("temperature_c") in (None, "")
    )
    location = old_location
    weather = old_weather
    warnings = []
    retry_location = location_needs_retry(old_location) and submitted_coordinates is not None
    if location_needs_metadata or weather_needs_metadata or retry_location:
        coordinates = submitted_coordinates if retry_location else (stored_coordinates or submitted_coordinates)
        if coordinates is None:
            warnings.append("当前连接未提供定位，天气和位置未记录。")
        else:
            latitude, longitude, accuracy = coordinates
            metadata = fetch_diary_metadata(
                latitude,
                longitude,
                accuracy,
                current_app.config["BLOG_AMAP_WEB_SERVICE_KEY"],
            )
            if better_location(old_location, metadata["location"]) or not stored_coordinates:
                location = metadata["location"]
            elif not retry_location:
                location = metadata["location"]
            if weather_needs_metadata:
                weather = metadata["weather"]
            warnings.extend(metadata["warnings"])

    new_image_path = None
    new_image_disk_path = None
    if uploaded_files:
        new_image_path, error_response = _store_uploaded_image(
            uploaded_files[0],
            current_app.config["BLOG_DIARY_IMAGE_UPLOAD_DIR"],
            int(current_app.config["BLOG_DIARY_IMAGE_MAX_BYTES"]),
            "日记图片",
        )
        if error_response:
            return error_response
        new_image_disk_path = os.path.join(
            current_app.config["BLOG_DIARY_IMAGE_UPLOAD_DIR"],
            *new_image_path.split("/"),
        )

    if new_image_path:
        image_url = new_image_path
    elif request.form.get("remove-image") == "1":
        image_url = ""
    elif existing_diary:
        image_url = existing_diary.image_url
    else:
        image_url = ""

    timestamp = now.isoformat(timespec="seconds")
    diary_entry = Diary(
        entry_date=today_date,
        content=content,
        image_url=image_url,
        created_at=(
            existing_diary.created_at
            if existing_diary and existing_diary.created_at
            else timestamp
        ),
        updated_at=timestamp,
        location=location,
        weather=weather,
    )

    try:
        result = dbHelper.save_today_diary(diary_entry, today_date)
    except ValueError as exc:
        if new_image_disk_path:
            try:
                os.remove(new_image_disk_path)
            except FileNotFoundError:
                pass
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        if new_image_disk_path:
            try:
                os.remove(new_image_disk_path)
            except OSError:
                pass
        raise

    return jsonify(
        {
            "status": "success",
            "operation": result["operation"],
            "message": result["message"],
            "detail_url": url_for(
                "main.diary_detail",
                year=today.year,
                month=today.month,
                day=today.day,
            ),
            "warnings": warnings,
        }
    )


@main.route('/diary/<int:year>/<int:month>/<int:day>')
@login_required
def diary_detail(year, month, day):
    try:
        entry_date = datetime(year, month, day).date()
    except ValueError:
        return render_template('404.html', **get_site_context()), 404

    diary_entry = dbHelper.get_diary_by_date(entry_date.isoformat())
    if diary_entry is None:
        return render_template('404.html', **get_site_context()), 404

    diary_entry.weekday_label = DIARY_WEEKDAY_LABELS[entry_date.weekday()]
    all_diaries = dbHelper.get_all_diaries()
    all_diaries.sort(key=lambda item: item.entry_date)
    for item in all_diaries:
        item.weekday_label = DIARY_WEEKDAY_LABELS[
            datetime.strptime(item.entry_date, "%Y-%m-%d").weekday()
        ]

    entry_dates = [item.entry_date for item in all_diaries]
    diary_index = entry_dates.index(diary_entry.entry_date)
    previous_diary = all_diaries[diary_index - 1] if diary_index > 0 else None
    next_diary = (
        all_diaries[diary_index + 1]
        if diary_index + 1 < len(all_diaries)
        else None
    )
    today = diary_date(datetime.now(ZoneInfo(current_app.config["BLOG_TIMEZONE"])))

    return render_template(
        'diary_detail.html',
        diary=diary_entry,
        is_today=entry_date == today,
        previous_diary=previous_diary,
        next_diary=next_diary,
        **get_site_context(),
    )

# ========================= 健身 =========================
FITNESS_CHART_DAYS = 30
_MAX_EXERCISES = 12
_MAX_SETS = 20


@main.route('/fitness', methods=['GET'])
@login_required
def fitness():
    timezone = ZoneInfo(current_app.config["BLOG_TIMEZONE"])
    today = diary_date(datetime.now(timezone))

    month_value = request.args.get("month", today.strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month_value):
        abort(400)
    archive_year, archive_month = int(month_value[:4]), int(month_value[5:])
    if (archive_year, archive_month) > (today.year, today.month):
        abort(400)

    workouts = dbHelper.get_all_workouts()
    volumes = volume_by_day(workouts)
    month_workouts = dbHelper.get_workouts_by_month(archive_year, archive_month)
    is_current_month = (archive_year, archive_month) == (today.year, today.month)
    today_workout = dbHelper.get_workout_by_date(today.isoformat()) if is_current_month else None

    first_of_month = date(archive_year, archive_month, 1)
    previous_month = first_of_month - timedelta(days=1) if first_of_month > date.min else None
    next_month = (first_of_month + timedelta(days=32)).replace(day=1)

    metrics = dbHelper.get_body_metrics()
    return render_template(
        'fitness.html',
        workouts=[_decorate_workout(workout) for workout in month_workouts
                  if workout.entry_date != today.isoformat()],
        today_workout=_decorate_workout(today_workout) if today_workout else None,
        today_date=today.isoformat(),
        today_weekday=DIARY_WEEKDAY_LABELS[today.weekday()],
        is_current_month=is_current_month,
        archive_year=archive_year,
        archive_month=archive_month,
        month_stats=month_summary(workouts, archive_year, archive_month),
        activity=fitness_summary(volumes, archive_year, today),
        month_calendar=build_fitness_month(volumes, archive_year, archive_month, today),
        year_overview=build_fitness_year(volumes, archive_year, today),
        chart=build_chart(workouts, FITNESS_CHART_DAYS, today),
        balance_rows=balance(workouts),
        record_rows=records(workouts),
        body_metrics=_body_metric_tiles(metrics, workouts),
        movements=MOVEMENTS,
        day_types=DAY_TYPES,
        weight_steps=weight_options(workouts),
        previous_month_value=previous_month.strftime("%Y-%m") if previous_month else None,
        next_month_value=None if is_current_month else next_month.strftime("%Y-%m"),
        today_month=today.strftime("%Y-%m"),
        last_session=_previous_session_label(workouts, today),
        repeat_template=_repeat_template(workouts, today),
        **get_site_context(),
    )


@main.route('/fitness/activity', methods=['GET'])
@login_required
def fitness_activity():
    today = diary_date(datetime.now(ZoneInfo(current_app.config["BLOG_TIMEZONE"])))
    year_value = request.args.get("year", str(today.year))
    if not re.fullmatch(r"[0-9]{1,4}", year_value) or not 1 <= int(year_value) <= today.year:
        return jsonify({"message": "请选择有效年份。"}), 400
    calendar_data = build_fitness_calendar(dbHelper.get_all_workouts(), int(year_value), today)
    response = jsonify(calendar_data)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@main.route('/fitness', methods=['POST'])
@login_required
def save_fitness():
    validate_csrf_token()
    today = diary_date(datetime.now(ZoneInfo(current_app.config["BLOG_TIMEZONE"])))
    today_date = today.isoformat()

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "提交格式不正确。"}), 400
    if payload.get("entry_date") not in (None, "", today_date):
        return jsonify({"status": "error", "message": "只能保存当天的训练，请刷新页面。"}), 409

    try:
        workout = _parse_workout_payload(payload, today_date)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    now = datetime.now(ZoneInfo(current_app.config["BLOG_TIMEZONE"])).isoformat(timespec="seconds")
    workout.created_at = workout.created_at or now
    workout.updated_at = now
    result = dbHelper.save_workout(workout, today_date)

    body_weight = _parse_number(payload.get("weight_kg"), 20, 300, "体重")
    if body_weight is not None:
        dbHelper.save_body_metric(BodyMetric(measured_date=today_date, weight_kg=body_weight))

    return jsonify({**result, "totals": workout_totals(workout)})


def _parse_workout_payload(payload, today_date):
    day_type = payload.get("day_type")
    if day_type not in DAY_TYPES:
        raise ValueError("请选择训练类型。")

    raw_exercises = payload.get("exercises") or []
    if not isinstance(raw_exercises, list) or len(raw_exercises) > _MAX_EXERCISES:
        raise ValueError("动作数量超出范围。")

    exercises = []
    for raw in raw_exercises:
        if not isinstance(raw, dict):
            raise ValueError("动作格式不正确。")
        name = raw.get("name")
        if name not in dict((item[0], item[1]) for item in MOVEMENTS):
            raise ValueError("不认识的动作：%s" % name)
        kind = movement_kind(name)
        raw_sets = raw.get("sets") or []
        if not isinstance(raw_sets, list) or not raw_sets or len(raw_sets) > _MAX_SETS:
            raise ValueError("「%s」的组数超出范围。" % name)
        exercises.append({"name": name, "sets": [_parse_set(entry, kind, name) for entry in raw_sets]})

    if day_type == "休息" and exercises:
        raise ValueError("休息日不该有动作。")
    if day_type != "休息" and not exercises:
        raise ValueError("至少记一个动作，或者把类型改成休息。")

    return Workout(
        entry_date=today_date,
        day_type=day_type,
        exercises=exercises,
        duration_min=_parse_number(payload.get("duration_min"), 1, 600, "训练时长", integer=True),
        rpe=_parse_number(payload.get("rpe"), 1, 10, "RPE", integer=True),
        note=str(payload.get("note") or "")[:2000],
    )


def _parse_set(entry, kind, name):
    if not isinstance(entry, dict):
        raise ValueError("「%s」的组格式不正确。" % name)
    note = str(entry.get("note") or "")[:120]
    if kind == "static":
        seconds = _parse_number(entry.get("seconds"), 1, 3600, "「%s」的时长" % name, integer=True)
        if seconds is None:
            raise ValueError("「%s」需要填时长。" % name)
        return {"seconds": seconds, "note": note}

    weight = _parse_number(entry.get("weight"), 0.5, 200, "「%s」的重量" % name)
    left = _parse_number(entry.get("left"), 1, 500, "「%s」的次数" % name, integer=True)
    right = _parse_number(entry.get("right"), 1, 500, "「%s」的次数" % name, integer=True)
    if weight is None and left is None and right is None and not note:
        raise ValueError("「%s」有空组，删掉它或者填上数字。" % name)
    if kind == "bilateral":
        # 双侧只有一个次数，存在 left 上；right 留空，别让它看起来像漏了一侧。
        return {"weight": weight, "left": left, "right": None, "note": note}
    # 只记了重量、次数没记下来是真实会发生的（历史记录里就有），照存，
    # 容量那天会标成“未记录”而不是零——路由不该比模型更严。
    return {"weight": weight, "left": left, "right": right, "note": note}


def _parse_number(value, minimum, maximum, label, integer=False):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s 需要是数字。" % label)
    if not minimum <= number <= maximum:
        raise ValueError("%s 超出合理范围。" % label)
    if integer:
        if number != int(number):
            raise ValueError("%s 需要是整数。" % label)
        return int(number)
    return round(number, 2)


def _decorate_workout(workout):
    """把模板要用的小计挂上去，模板里不再算数。"""
    workout.weekday_label = DIARY_WEEKDAY_LABELS[
        datetime.strptime(workout.entry_date, "%Y-%m-%d").weekday()
    ]
    workout.totals = workout_totals(workout)
    workout.exercise_rows = [exercise_totals(exercise) for exercise in workout.exercises]
    return workout


def _previous_session_label(workouts, today):
    for workout in workouts:
        if workout.entry_date < today.isoformat():
            day = date.fromisoformat(workout.entry_date)
            return "上次是 %d 月 %d 日 %s" % (day.month, day.day, workout.day_type)
    return "还没有训练记录"


def _repeat_template(workouts, today):
    """上一次训练的动作与重量，供「套用上次」。次数不带——那要当场练出来。"""
    for workout in workouts:
        if workout.entry_date < today.isoformat() and workout.exercises:
            return [
                {
                    "name": exercise.get("name"),
                    "sets": [{"weight": entry.get("weight")} for entry in exercise.get("sets") or []],
                }
                for exercise in workout.exercises
            ]
    return []


def _body_metric_tiles(metrics, workouts):
    """体重、腰围各取最新一条，平板支撑直接从训练记录里取，不重复记。"""
    weights = [metric for metric in metrics if metric.weight_kg]
    waists = [metric for metric in metrics if metric.waist_cm]
    planks = sorted(
        (
            (workout.entry_date, max(entry.get("seconds") or 0 for entry in exercise["sets"]))
            for workout in workouts
            for exercise in workout.exercises
            if movement_kind(exercise.get("name")) == "static" and exercise.get("sets")
        ),
        key=lambda item: item[0],
    )
    return {
        "weight": weights[-1] if weights else None,
        "weight_first": weights[0] if weights else None,
        "waist": waists[-1] if waists else None,
        "plank": planks[-1] if planks else None,
        "plank_previous": planks[-2] if len(planks) > 1 else None,
    }


@main.route('/edit/cover', methods=['POST'])
@login_required
def upload_cover_image():
    validate_csrf_token()

    max_bytes = int(current_app.config.get("BLOG_COVER_MAX_BYTES", 5 * 1024 * 1024))
    relative_path, error_response = _store_uploaded_image(
        request.files.get("cover-image"),
        current_app.config["BLOG_COVER_UPLOAD_DIR"],
        max_bytes,
        "封面图片",
    )
    if error_response:
        return error_response

    cover_url = "/media/covers/{0}".format(relative_path)
    return jsonify({"status": "success", "cover_url": cover_url})


@main.route('/edit/article-image', methods=['POST'])
@login_required
def upload_article_image():
    validate_csrf_token()

    max_bytes = int(
        current_app.config.get("BLOG_ARTICLE_IMAGE_MAX_BYTES", 10 * 1024 * 1024)
    )
    relative_path, error_response = _store_uploaded_image(
        request.files.get("article-image"),
        current_app.config["BLOG_ARTICLE_IMAGE_UPLOAD_DIR"],
        max_bytes,
        "正文图片",
    )
    if error_response:
        return error_response

    image_url = "/media/articles/{0}".format(relative_path)
    return jsonify({"status": "success", "image_url": image_url})

@main.route('/edit', methods=['GET', 'POST'])
@login_required
def edit_blog():
    if request.method == 'POST':
        validate_csrf_token()
        blog = Blog()
        blog.html_title = request.form.get('html-title', '')
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog.category = request.form['category']
        try:
            blog.cover_url = normalize_cover_url(request.form.get('cover-url', ''))
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        if request.form['month'] != '':
            blog.month = request.form['month']
        if request.form['year'] != '':
            blog.year = request.form['year']
        if request.form['date'] != '':
            blog.date = request.form['date']
        if request.form['time'] != '':
            blog.time = request.form['time']

        action = request.form.get('action')

        response = {"status":"default_failed", "message":"操作失败"}
        if action == "update":
            # 更新博客
            original_key = (
                request.form.get('original-year') or blog.year,
                request.form.get('original-month') or blog.month,
                request.form.get('original-html-title') or blog.html_title,
            )
            response = dbHelper.update_blog(blog, original_key=original_key)
        elif action == "insert":
            # 插入新博客
            response = dbHelper.insert_blog(blog)
        elif action == "insert_new":
            # 兼容旧前端动作，具体去重交给数据库层统一处理
            response = dbHelper.insert_blog(blog)

        return response
    
    categories = dbHelper.get_all_categories()
    return render_template(
        'edit.html',
        blog=None,
        blog_content=None,
        categories=categories,
        **get_site_context(),
    )

@main.route('/<int:year>/<int:month>/<string:html_title>')
def blog_detail(year, month, html_title):
    # 根据年月和标题获取博客内容
    blog = dbHelper.get_specify_blog(str(year), str(month), html_title)
    
    if not blog:
        return render_template('404.html', **get_site_context()), 404

    article_view_tracking = _article_view_tracking_config(blog)
    return render_template(
        'blog_detail.html',
        blog=blog,
        article_view_tracking=article_view_tracking,
        **get_site_context(),
    )


@main.route('/track/article-view', methods=['POST'])
def track_article_view():
    validate_csrf_token()

    if current_admin_authenticated():
        return jsonify({"status": "ignored", "reason": "admin"})

    client_ip = _get_client_ip()
    if dbHelper.is_excluded_article_view_ip(client_ip):
        return jsonify({"status": "ignored", "reason": "excluded_ip"})

    if (
        is_crawler_user_agent(request.headers.get("User-Agent", ""))
        or is_verified_crawler_ip(client_ip)
    ):
        return jsonify({"status": "ignored", "reason": "crawler"})

    if is_loopback_ip(client_ip):
        return jsonify({"status": "ignored", "reason": "local_test"})

    payload = request.get_json(silent=True) or {}
    reading_seconds = normalize_reading_seconds(payload.get("reading_seconds"))
    if not is_effective_reading_seconds(reading_seconds):
        return jsonify({"status": "ignored", "reason": "short_view"})

    view_session_id = str(payload.get("view_session_id") or "").strip()
    if not view_session_id:
        return jsonify({"status": "error", "message": "missing view_session_id"}), 400

    year = str(payload.get("year") or "").strip()
    month = str(payload.get("month") or "").strip()
    html_title = str(payload.get("html_title") or "").strip()
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return jsonify({"status": "error", "message": "article not found"}), 404

    path = url_for(
        "main.blog_detail",
        year=int(blog.year),
        month=int(blog.month),
        html_title=blog.html_title,
    )

    try:
        view_record = dbHelper.record_or_update_article_view_session(
            blog,
            client_ip,
            path,
            view_session_id,
            reading_seconds,
        )
    except Exception as exc:
        print("article view record failed: {0}".format(exc))
        return jsonify({"status": "error", "message": "record failed"}), 500

    return jsonify(
        {
            "status": "recorded",
            "reading_seconds": view_record.get("reading_seconds", 0),
            "reading_time_label": view_record.get("reading_time_label", "未记录"),
        }
    )

@main.route('/manage')
@login_required
def blog_manage():
    """
    博客管理页面
    """
    blogs = dbHelper.get_all_blogs()
    return render_template('manage.html', blogs=blogs, **get_site_context())

@main.route('/manage/views')
@login_required
def article_view_manage():
    """
    文章浏览量统计页面
    """
    view_dashboard = dbHelper.get_article_view_dashboard(recent_limit=100)
    return render_template(
        'view_stats.html',
        view_dashboard=view_dashboard,
        excluded_ip_error=None,
        **get_site_context(),
    )


@main.route('/manage/views/excluded-ips', methods=['POST'])
@login_required
def add_excluded_article_view_ip():
    validate_csrf_token()
    try:
        dbHelper.add_excluded_article_view_ip(
            request.form.get("ip"),
            request.form.get("label"),
        )
    except ValueError as exc:
        return _render_article_view_manage(excluded_ip_error=str(exc), status_code=400)

    return redirect(url_for('main.article_view_manage'))


@main.route('/manage/views/excluded-ips/update', methods=['POST'])
@login_required
def update_excluded_article_view_ip():
    validate_csrf_token()
    try:
        dbHelper.update_excluded_article_view_ip(
            request.form.get("original_ip"),
            request.form.get("ip"),
            request.form.get("label"),
        )
    except ValueError as exc:
        return _render_article_view_manage(excluded_ip_error=str(exc), status_code=400)

    return redirect(url_for('main.article_view_manage'))


@main.route('/manage/views/excluded-ips/delete', methods=['POST'])
@login_required
def delete_excluded_article_view_ip():
    validate_csrf_token()
    try:
        dbHelper.delete_excluded_article_view_ip(request.form.get("original_ip"))
    except ValueError as exc:
        return _render_article_view_manage(excluded_ip_error=str(exc), status_code=400)

    return redirect(url_for('main.article_view_manage'))

@main.route('/edit/<string:year>/<string:month>/<string:html_title>')
@login_required
def manage_edit_blog(year, month, html_title):
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return render_template('404.html', **get_site_context()), 404
    
    blog_content = json.dumps(blog.content)
    categories = dbHelper.get_all_categories()
    return render_template(
        'edit.html',
        blog=blog,
        blog_content=blog_content,
        categories=categories,
        **get_site_context(),
    )

@main.route('/delete/<string:year>/<string:month>/<string:html_title>', methods=['POST'])
@login_required
def manage_delete_blog(year, month, html_title):
    validate_csrf_token()
    blog = dbHelper.get_specify_blog(year, month, html_title)
    if blog is None:
        return jsonify({"status": "error", "message": "指定的博客不存在。"}), 404
    
    return dbHelper.delete_blog(blog)  # 删除博客

@main.route('/register')
def register():
    return redirect(url_for('main.index'))
    
@main.route('/logout', methods=['POST'])
@login_required
def logout():
    return admin_logout()

    

@main.route('/categorized_blogs/<string:categoryName>')
def categorized_blogs(categoryName):
    blogs = dbHelper.get_blogs_by_category(categoryName)
    # 按最新时间排序blogs
    blogs.reverse()    
    return init_index_with_blogs(blogs)

@main.route('/date_blogs/<string:year>/<string:month>')
def archived_blogs(year, month):
    blogs = dbHelper.get_blogs_by_date(year, month)
    blogs.reverse()  # 按最新时间排序blogs
    return init_index_with_blogs(blogs)

# 添加评论
def add_comment(blog_id, comment):
    pass


def _article_view_tracking_config(blog):
    if current_admin_authenticated():
        return None

    client_ip = _get_client_ip()
    if is_crawler_user_agent(request.headers.get("User-Agent", "")):
        return None

    if (
        dbHelper.is_excluded_article_view_ip(client_ip)
        or is_loopback_ip(client_ip)
        or is_verified_crawler_ip(client_ip)
    ):
        return None

    return {
        "endpoint": url_for("main.track_article_view"),
        "year": blog.year,
        "month": blog.month,
        "html_title": blog.html_title,
        "minimum_seconds": EFFECTIVE_VIEW_SECONDS,
        "heartbeat_seconds": READING_HEARTBEAT_SECONDS,
    }


def _get_client_ip():
    if current_app.config.get("BLOG_TRUST_PROXY_HEADERS"):
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded_for.split(",", 1)[0].strip()
        if forwarded_ip:
            return forwarded_ip

        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip

    return request.remote_addr or ""


def _render_article_view_manage(excluded_ip_error=None, status_code=200):
    view_dashboard = dbHelper.get_article_view_dashboard(recent_limit=100)
    return (
        render_template(
            'view_stats.html',
            view_dashboard=view_dashboard,
            excluded_ip_error=excluded_ip_error,
            **get_site_context(),
        ),
        status_code,
    )
