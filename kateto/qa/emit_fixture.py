import argparse
import json
import sys

from pydantic import ValidationError

from kateto.core.event import EventEnvelope, TranscriptionData


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=["transcription"])
    parser.add_argument("--text")
    args = parser.parse_args()
    try:
        envelope = EventEnvelope[TranscriptionData](
            name=args.event,
            data=TranscriptionData(text=args.text),
            source="qa_fixture",
        )
    except ValidationError as error:
        print(f"ValidationError: {error}", file=sys.stderr)
        return 2
    print(json.dumps(json.loads(envelope.model_dump_json()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
