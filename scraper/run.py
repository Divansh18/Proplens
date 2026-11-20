import argparse
import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.schemas.document import Document
from scraper.base import BaseScraper
from scraper.darglobal import DarGlobalScraper, import_saved_html
from scraper.parsing import dedupe_documents
from scraper.wasalt import WasaltScraper

logger = logging.getLogger(__name__)


def write_documents(path: Path, documents: list[Document]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                [document.model_dump(mode="json") for document in documents],
                temporary,
                ensure_ascii=False,
                indent=2,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_documents(path: Path) -> list[Document]:
    if not path.exists():
        return []
    try:
        return [Document.model_validate(item) for item in json.loads(path.read_text())]
    except (OSError, ValueError) as exc:
        logger.warning("Could not read existing data file %s: %s", path, exc)
        return []


async def run_source(
    source: str, limit: int, data_dir: Path, from_html: Path | None = None
) -> None:
    output = data_dir / f"{source}.json"
    if from_html is not None:
        imported, skipped, errors = import_saved_html(from_html, limit)
        official = [
            doc
            for doc in read_documents(output)
            if doc.metadata.get("data_source") != "browser_saved_html"
        ]
        documents = dedupe_documents(official + imported)
        write_documents(output, documents)
        logger.info(
            "source=darglobal mode=browser_html files_imported=%d records_saved=%d "
            "records_skipped=%d errors=%d",
            len(imported),
            len(documents),
            skipped,
            len(errors),
        )
        for error in errors:
            logger.warning("source=darglobal import_error=%s", error)
        return

    scraper: BaseScraper = (
        DarGlobalScraper(limit) if source == "darglobal" else WasaltScraper(limit)
    )
    documents: list[Document] = []
    try:
        documents = await scraper.scrape()
    except Exception:
        logger.exception("Scraper failed source=%s", source)
    finally:
        await scraper.close()
    if source == "darglobal":
        previous = read_documents(output)
        if not documents and scraper.blocked_reason:
            documents = previous
        else:
            manual = [
                doc for doc in previous if doc.metadata.get("data_source") == "browser_saved_html"
            ]
            documents = dedupe_documents(documents + manual)
    write_documents(output, documents)
    logger.info(
        "source=%s pages_fetched=%d records_saved=%d records_skipped=%d errors=%d blocked=%s",
        source,
        scraper.pages_fetched,
        len(documents),
        scraper.records_skipped,
        len(scraper.errors),
        scraper.blocked_reason or "no",
    )
    for error in scraper.errors:
        logger.warning("source=%s page_error=%s", source, error)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("limit must be at least 1")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape public property project data")
    parser.add_argument("--source", choices=("all", "darglobal", "wasalt"), default="all")
    parser.add_argument("--limit", type=positive_int, default=150)
    parser.add_argument("--from-html", type=Path, metavar="DIRECTORY")
    args = parser.parse_args()
    if args.from_html is not None:
        if args.source != "darglobal":
            parser.error("--from-html requires --source darglobal")
        if not args.from_html.is_dir():
            parser.error(f"HTML directory does not exist: {args.from_html}")
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sources = ("darglobal", "wasalt") if args.source == "all" else (args.source,)

    async def run_all() -> None:
        for source in sources:
            await run_source(source, args.limit, settings.data_dir, args.from_html)

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
