"""Validate structured replies and render ordinary UTF-8 text documents."""
from __future__ import annotations

import re
from pathlib import Path


class InvalidReply(ValueError):
    pass


def clean_field(payload, name, limit=200):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidReply(f'{name} must be a non-empty string')
    value = value.strip()
    if len(value) > limit:
        raise InvalidReply(f'{name} exceeds {limit} characters')
    return value


def render_document(payload, minimum_cjk=0):
    location = clean_field(payload, 'location', 80)
    scene_time = clean_field(payload, 'scene_time', 80)
    body = clean_field(payload, 'body', 20000)
    mood = clean_field(payload, 'mood', 80)
    rationale = clean_field(payload, 'brief_note', 200)
    for value in [location, scene_time, mood]:
        if '\n' in value or '\r' in value:
            raise InvalidReply('Header and status fields must each fit on one line')
    score = payload.get('relationship_value')
    if type(score) is not int or not 0 <= score <= 100:
        raise InvalidReply('relationship_value must be an integer from 0 to 100')
    options = payload.get('options')
    if not isinstance(options, list) or len(options) != 4:
        raise InvalidReply('options must contain exactly four choices')
    normalized = []
    for option in options:
        if not isinstance(option, str) or not option.strip() or len(option) > 200 or '\n' in option or '\r' in option:
            raise InvalidReply('Each option must be a non-empty single line of at most 200 characters')
        normalized.append(option.strip())
    if len(set(normalized)) != 4:
        raise InvalidReply('The four choices must be different')
    count = len(re.findall(r'[\u4e00-\u9fff]', body))
    if count < minimum_cjk:
        raise InvalidReply(f'body contains {count} Chinese characters; this first reply requires at least {minimum_cjk}. Expand the actual scene without repetition, then call again with the same route_token.')
    values = '\n'.join([location, scene_time, body, mood, rationale, *normalized])
    if re.search(r'</?(?:think|analysis|reasoning)>', values, flags=re.I):
        raise InvalidReply('Do not include hidden-reasoning tags; brief_note is a short visible explanation only')
    token = payload.get('route_token')
    if token and token in values:
        raise InvalidReply('Do not expose route_token in the document')
    return (
        f'【{location}/{scene_time}】\n\n{body}\n\n'
        f'────────────────────\n心情：{mood}\n关系温度：{score}/100\n\n'
        + '\n'.join(f'{letter}. {option}' for letter, option in zip('ABCD', normalized))
        + f'\n\n简要说明：{rationale}\n'
    )


def write_document(directory, filename, text):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r'fus-[0-9a-f]{32}\.txt', filename):
        raise ValueError('Invalid generated document name')
    path = directory / filename
    if path.resolve().parent != directory.resolve():
        raise ValueError('Document path escaped the output directory')
    # A BOM keeps Chinese readable in Windows text viewers.
    with path.open('x', encoding='utf-8-sig', newline='\r\n') as stream:
        stream.write(text)
    return path
