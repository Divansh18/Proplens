import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.schemas.document import Document, PropertySource

logger = logging.getLogger(__name__)
SOURCES: tuple[PropertySource, ...] = ("darglobal", "wasalt")


def load_documents(data_dir: Path) -> tuple[list[Document], dict[str, int]]:
    documents: list[Document] = []
    counts = {source: 0 for source in SOURCES}
    for source in SOURCES:
        path = data_dir / f"{source}.json"
        if not path.exists():
            logger.warning("Data file missing: %s", path)
            continue
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("expected a JSON list")
        except (OSError, ValueError) as exc:
            logger.error("Could not load %s: %s", path, exc)
            continue
        for index, record in enumerate(records):
            try:
                document = Document.model_validate(record)
            except ValidationError as exc:
                logger.warning("Invalid document in %s at index %d: %s", path, index, exc)
                continue
            if document.source != source:
                logger.warning("Wrong source in %s at index %d", path, index)
                continue
            documents.append(document)
            counts[source] += 1
        logger.info("Loaded %d %s documents from %s", counts[source], source, path)
    return documents, counts
