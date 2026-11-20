import re

from app.retrieval.base import SearchResult
from app.retrieval.filters import QueryFilters


def _listing_rows(
    results: list[SearchResult], reply: str, filters: QueryFilters, show_all: bool = False
) -> list[tuple[int, SearchResult]]:
    listings = [
        (index, result)
        for index, result in enumerate(results, start=1)
        if result.document.source == "wasalt" and result.document.metadata.get("type") == "listing"
    ]
    if filters.price_sort:
        return listings[:3]
    if show_all:
        return listings
    citations = {int(number) for number in re.findall(r"\[(\d+)\]", reply)}
    cited = [row for row in listings if row[0] in citations]
    return cited or listings[:1]


def _field(value: object, arabic: bool) -> str:
    if value in (None, ""):
        return "غير مذكور" if arabic else "Not provided"
    return str(value).strip()


def _area(metadata: dict[str, object], arabic: bool) -> str:
    value = metadata.get("area_sqm")
    if value in (None, ""):
        return _field(None, arabic)
    area = f"{value} sqm"
    if metadata.get("area_unverified"):
        note = "كما ورد في Wasalt؛ غير مؤكد" if arabic else "reported by Wasalt; unverified"
        return f"{area} ({note})"
    return area


def append_listing_details(
    reply: str,
    results: list[SearchResult],
    filters: QueryFilters,
    arabic: bool = False,
    show_all: bool = False,
) -> str:
    reply = re.split(
        r"\n\s*(?:Wasalt listing details:|Lowest-priced options \(including the next two\):|"
        r"Highest-priced options \(including the next two\):|تفاصيل عقارات Wasalt:|"
        r"أقل الأسعار \(مع الخيارين التاليين\):|أعلى الأسعار \(مع الخيارين التاليين\):)",
        reply,
        maxsplit=1,
    )[0].rstrip()
    rows = _listing_rows(results, reply, filters, show_all)
    if not rows:
        return reply
    for _index, result in rows:
        metadata = result.document.metadata
        if metadata.get("area_unverified") and metadata.get("area_sqm"):
            area = str(metadata["area_sqm"])
            note = "كما ورد في Wasalt؛ غير مؤكد" if arabic else "reported by Wasalt; unverified"
            reply = re.sub(
                rf"\b{re.escape(area)}\s*(?:sqm|m²)\b",
                f"{area} sqm ({note})",
                reply,
                flags=re.IGNORECASE,
            )
    if arabic:
        heading = "تفاصيل عقارات Wasalt:"
        if filters.price_sort == "asc":
            heading = "أقل الأسعار (مع الخيارين التاليين):"
        elif filters.price_sort == "desc":
            heading = "أعلى الأسعار (مع الخيارين التاليين):"
        labels = ("المدينة", "الحي", "السعر", "المساحة", "غرف النوم", "رابط الإعلان")
    else:
        heading = "Wasalt listing details:"
        if filters.price_sort == "asc":
            heading = "Lowest-priced options (including the next two):"
        elif filters.price_sort == "desc":
            heading = "Highest-priced options (including the next two):"
        labels = ("City", "District", "Price", "Area", "Bedrooms", "Listing link")
    lines = [heading]
    for index, result in rows:
        document = result.document
        metadata = document.metadata
        lines.append(
            f"- **{document.title}** [{index}] — "
            f"{labels[0]}: {_field(metadata.get('city'), arabic)}; "
            f"{labels[1]}: {_field(metadata.get('district'), arabic)}; "
            f"{labels[2]}: {_field(metadata.get('price'), arabic)}; "
            f"{labels[3]}: {_area(metadata, arabic)}; "
            f"{labels[4]}: {_field(metadata.get('bedrooms'), arabic)}; "
            f"{labels[5]}: {document.url}"
        )
    details = "\n".join(lines)
    return f"{reply}\n\n{details}" if reply else details
