"""Minimal i18n for the queue bot (per-chat language, en default)."""

LANGUAGES = ("en", "ru")

LANGS = {
    "en": "English",
    "ru": "Русский",
}


def tr(lang, key, **kwargs):
    """Translate key to lang, falling back to English."""
    table = STRINGS.get(lang) or STRINGS["en"]
    tpl = table.get(key) or STRINGS["en"].get(key, key)
    if kwargs:
        return tpl.format(**kwargs)
    return tpl


STRINGS = {
    "en": {
        # queue message
        "queue_title": "<b>Lesson Queue</b>",
        "queue_when": "{day} {time}",
        # buttons
        "btn_join": "Join",
        "btn_leave": "Leave",
        # toasts
        "toast_joined": "You're #{pos}",
        "toast_left": "You left the queue",
        "toast_not_in_queue": "You're not in the queue",
        "toast_queue_closed": "Queue isn't open yet",
        "toast_already_in": "You're already in, #{pos}",
        "toast_admins_only": "Admins only",
        # /start /info
        "welcome_body": "Send /info to see the commands and current settings.",
        "config_header": "<b>Current settings</b>",
        "config_empty": "<b>Not configured</b>",
        "config_empty_hint": "/setlesson &lt;Day&gt; &lt;HH:MM&gt; - example: /setlesson Monday 23:00",
        "commands_header": "<b>Commands</b>",
        "admin_header": "<b>Admins only</b>",
        "student_queue": "join today's queue",
        "student_leave": "leave the queue",
        "student_setname": "set your display name in the queue",
        "student_info": "current settings & commands",
        "student_lang": "choose the language",
        "admin_setlesson": "add/update a lesson (day and time)",
        "admin_before": "minutes before the lesson when the queue opens",
        "admin_duration": "how long the list stays after the lesson starts",
        "admin_delete": "remove a lesson for a day",
        "admin_tz": "set the chat's timezone",
        "lesson_desc": "opens {ob} min before, accepts joins for {lt} min",
        "label_before": "Open-before",
        "label_duration": "Join window after start",
        # queue commands
        "q_closed": "This queue isn't accepting joins right now.",
        "q_none_open": "No queue is open right now.",
        "q_already_in": "You're already in the queue!",
        "q_joined_at": "{name}, you're #{pos} in the queue for {label}.",
        "q_not_in": "You're not in the queue.",
        "q_left": "Removed from queue. You were #{pos}.",
        "usage_setname": "Usage: /setname <name>\nExample: /setname Amir Abu Yunus",
        "prompt_setname": "Enter your display name:",
        "prompt_expired": "That prompt expired. Send the command again (e.g. /setname).",
        "setname_set": "Display name set to {name}.",
        "setname_too_long": "Name too long (max 60 characters).",
        # config commands
        "admin_only": "Only chat admins can configure lessons.",
        "need_admin_rights": "The bot needs admin rights with <b>Pin messages</b> and <b>Delete messages</b>.\nPromote the bot to admin in this chat, then try again.",
        "usage_setlesson": "Usage: /setlesson <day> <HH:MM>\nExample: /setlesson Monday 23:00",
        "prompt_setlesson": "Enter day and time (e.g. Monday 23:00):",
        "prompt_setlesson_day": "Choose a day of the week:",
        "prompt_setlesson_time": "Enter time (HH:MM), e.g. 23:00:",
        "setlesson_day_picked": "Day: {day}. Now enter the time.",
        "invalid_input": "Invalid input. Days: Monday..Sunday. Time: HH:MM (e.g. 23:00).",
        "invalid_time": "Invalid time. Use HH:MM (e.g. 23:00).",
        "lesson_overlap": "This lesson overlaps with an existing one ({other} {time}, opens {ob} min before, lifetime {lt} min).",
        "lesson_set": "Lesson set: {day} {time}\nQueue opens {ob} min before.",
        "usage_window": "Usage: {cmd} [day] <minutes>\nExample: {cmd} 30 or {cmd} Monday 30",
        "prompt_before": "Enter minutes (optionally with day, e.g. 30 or Monday 30):",
        "prompt_duration": "Enter minutes (optionally with day, e.g. 30 or Monday 30):",
        "value_range": "Value must be between 1 and 1440 minutes.",
        "no_lesson_yet": "No lesson configured yet. Use /setlesson <day> <HH:MM> first.",
        "window_set": "Lesson {day} {time}: {label} = {value} min.",
        "invalid_day": "Invalid day. Days: Monday..Sunday.",
        "no_lesson_day": "No lesson for {day}.",
        "removed_lesson": "Removed lesson for {day}.",
        "usage_delete": "Usage: /delete <day>\nExample: /delete Monday",
        "prompt_delete": "Enter the day to remove (e.g. Monday):",
        # /lang
        "lang_prompt": "<b>Language / Язык</b>\n\nSelect the chat's language:",
        "lang_set": "Language set to {lang}.",
        # /tz
        "tz_title": "<b>Timezone / Часовой пояс</b>",
        "tz_current": "Current: {zone} ({label})",
        "tz_pick_hint": "Tap a zone below or send /tz &lt;Zone&gt; (e.g. /tz Asia/Almaty).",
        "tz_set": "Timezone set to {zone} ({label}).",
        "tz_invalid": "Unknown timezone: {value}. Use an IANA name like Asia/Almaty or UTC+03:00.",
    },
    "ru": {
        # queue message
        "queue_title": "<b>Очередь на урок</b>",
        "queue_when": "{day} {time}",
        # buttons
        "btn_join": "Встать",
        "btn_leave": "Выйти",
        # toasts
        "toast_joined": "Ты #{pos}",
        "toast_left": "Вышел(-а) из очереди",
        "toast_not_in_queue": "Ты не в очереди",
        "toast_queue_closed": "Очередь ещё не открыта",
        "toast_already_in": "Ты уже в очереди, #{pos}",
        "toast_admins_only": "Только админ",
        # /start /info
        "welcome_body": "Отправь /info, чтобы увидеть команды и текущие настройки.",
        "config_header": "<b>Текущие настройки</b>",
        "config_empty": "<b>Не настроено</b>",
        "config_empty_hint": "/setlesson &lt;День&gt; &lt;ЧЧ:ММ&gt; - пример: /setlesson Понедельник 23:00",
        "commands_header": "<b>Команды</b>",
        "admin_header": "<b>Только для админов</b>",
        "student_queue": "встать в очередь",
        "student_leave": "выйти из очереди",
        "student_setname": "задать своё имя в очереди",
        "student_info": "текущие настройки и команды",
        "student_lang": "выбрать язык",
        "admin_setlesson": "задать/обновить урок (день и время)",
        "admin_before": "за сколько минут до урока открыть очередь",
        "admin_duration": "сколько минут список живёт после начала урока",
        "admin_delete": "удалить урок для дня",
        "admin_tz": "часовой пояс чата",
        "lesson_desc": "открытие за {ob} мин, записи принимаются {lt} мин",
        "label_before": "Открытие очереди",
        "label_duration": "Приём записей после начала",
        # queue commands
        "q_closed": "Эта очередь сейчас не принимает записи.",
        "q_none_open": "Сейчас очередь не открыта.",
        "q_already_in": "Ты уже в очереди!",
        "q_joined_at": "{name}, ты #{pos} в очереди на {label}.",
        "q_not_in": "Ты не в очереди.",
        "q_left": "Убран из очереди. Ты был(а) #{pos}.",
        "usage_setname": "Использование: /setname <имя>\nПример: /setname Амир Абу Юнус",
        "prompt_setname": "Введите имя в очереди:",
        "prompt_expired": "Запрос устарел. Отправьте команду снова (например /setname).",
        "setname_set": "Имя в очереди: {name}.",
        "setname_too_long": "Слишком длинное имя (макс. 60 символов).",
        # config commands
        "admin_only": "Только админы чата могут настраивать уроки.",
        "need_admin_rights": "Боту нужны права админа: <b>Pin messages</b> и <b>Delete messages</b>.\nВыдай боту админку в этом чате и попробуй снова.",
        "usage_setlesson": "Использование: /setlesson <день> <ЧЧ:ММ>\nПример: /setlesson Понедельник 23:00",
        "prompt_setlesson": "Введите день и время (например Понедельник 23:00):",
        "prompt_setlesson_day": "Выберите день недели:",
        "prompt_setlesson_time": "Введите время (ЧЧ:ММ), например 23:00:",
        "setlesson_day_picked": "День: {day}. Теперь введите время.",
        "invalid_input": "Неверный ввод. Дни: Monday..Sunday. Время: ЧЧ:ММ (например 23:00).",
        "invalid_time": "Неверное время. Формат ЧЧ:ММ (например 23:00).",
        "lesson_overlap": "Урок пересекается с существующим ({other} {time}, открывается за {ob} мин, живёт {lt} мин).",
        "lesson_set": "Урок задан: {day} {time}\nочередь открывается за {ob} мин.",
        "usage_window": "Использование: {cmd} [день] <минуты>\nПример: {cmd} 30 или {cmd} Понедельник 30",
        "prompt_before": "Введите минуты (можно с днём, например 30 или Понедельник 30):",
        "prompt_duration": "Введите минуты (можно с днём, например 30 или Понедельник 30):",
        "value_range": "Значение должно быть от 1 до 1440 минут.",
        "no_lesson_yet": "Урок ещё не настроен. Сначала /setlesson <день> <ЧЧ:ММ>.",
        "window_set": "Урок {day} {time}: {label} = {value} мин.",
        "invalid_day": "Неверный день. Дни: Monday..Sunday.",
        "no_lesson_day": "Нет урока для {day}.",
        "removed_lesson": "Урок для {day} удалён.",
        "usage_delete": "Использование: /delete <день>\nПример: /delete Понедельник",
        "prompt_delete": "Введите день для удаления (например Понедельник):",
        # /lang
        "lang_prompt": "<b>Язык / Language</b>\n\nВыбери язык чата:",
        "lang_set": "Язык установлен: {lang}.",
        # /tz
        "tz_title": "<b>Часовой пояс / Timezone</b>",
        "tz_current": "Сейчас: {zone} ({label})",
        "tz_pick_hint": "Выбери пояс ниже или отправь /tz &lt;Zone&gt; (например /tz Asia/Almaty).",
        "tz_set": "Часовой пояс установлен: {zone} ({label}).",
        "tz_invalid": "Неизвестный пояс: {value}. Используй IANA-имя типа Asia/Almaty или UTC+03:00.",
    },
}