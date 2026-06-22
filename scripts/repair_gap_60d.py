import json
from sequoia_x.core.config import get_settings
from sequoia_x.data.engine import DataEngine


def main() -> None:
    with open('data/gap_60d_symbols.json', 'r', encoding='utf-8') as f:
        symbols = json.load(f)

    engine = DataEngine(get_settings())
    summary = engine.repair_history(
        symbols=symbols,
        workers=4,
        chunk_size=120,
        max_retries=3,
        resume=False,
    )
    print(summary)


if __name__ == '__main__':
    main()
