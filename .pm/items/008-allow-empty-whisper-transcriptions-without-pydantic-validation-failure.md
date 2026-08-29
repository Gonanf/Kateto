+++
id = 8
title = 'Allow empty Whisper transcriptions without Pydantic validation failure'
description = "Change WhisperResponse.text from min_length=1 to default='' to handle silent or non-speech VAD segments cleanly without raising ValidationError."
state = 'done'
type = 'fix'
created = '2026-08-29T00:46:09-03:00'
updated = '2026-08-29T00:46:09-03:00'
+++
