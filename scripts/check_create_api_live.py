"""Check invalid create requests against a running local API."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_json(path):
    with urlopen(BASE_URL + path, timeout=10) as response:
        return json.load(response)


def main():
    try:
        spec = get_json("/openapi.json")
        schemas = spec["components"]["schemas"]
        limits = {
            "title_max": schemas["PostCreate"]["properties"]["title"].get("maxLength"),
            "content_max": schemas["PostCreate"]["properties"]["content"].get("maxLength"),
            "filename_max": schemas["ImageCreate"]["properties"]["filename"].get("maxLength"),
            "post_extra_fields_allowed": schemas["PostCreate"].get("additionalProperties"),
            "image_extra_fields_allowed": schemas["ImageCreate"].get("additionalProperties"),
        }
        if limits != {"title_max": 255, "content_max": 100000, "filename_max": 255,
                      "post_extra_fields_allowed": False, "image_extra_fields_allowed": False}:
            raise ValueError("Updated schema not loaded.")
        before = {path: sorted(row["id"] for row in get_json(path)) for path in ("/images", "/posts")}
        # Each payload also omits a required field. This keeps the probe invalid
        # even if an older server has not loaded the new targeted validator.
        cases = [
            ("blank_post_title", "/posts", {"title": " ", "content": "Validation probe."}, "title"),
            ("blank_post_content", "/posts", {"title": "Validation probe", "content": " "}, "content"),
            ("oversized_post_title", "/posts", {"title": "t" * 256}, "title"),
            ("oversized_post_content", "/posts", {"title": "Probe", "content": "c" * 100001}, "content"),
            ("oversized_external_id", "/posts", {"external_id": "p" * 101, "title": "Probe"}, "external_id"),
            ("incorrect_post_field_type", "/posts", {"title": 123, "content": "Probe"}, "title"),
            ("unexpected_tenant_field", "/posts", {"title": "Probe", "content": "Probe", "tenant_id": 2}, "tenant_id"),
            ("blank_image_source", "/images", {"external_id": "probe", "filename": "fox.jpg", "source": " "}, "source"),
            ("oversized_image_filename", "/images", {"external_id": "probe", "filename": "f" * 256, "source": "probe"}, "filename"),
            ("image_path_traversal", "/images", {"external_id": "probe", "filename": "../fox.jpg", "source": "probe"}, "filename"),
            ("reserved_windows_filename", "/images", {"external_id": "probe", "filename": "CON.jpg", "source": "probe"}, "filename"),
            ("unsupported_image_format", "/images", {"external_id": "probe", "filename": "fox.gif", "source": "probe"}, "filename"),
            ("non_http_source_url", "/images", {"filename": "fox.jpg", "source": "probe", "source_page_url": "file:///C:/fox.jpg"}, "source_page_url"),
        ]
        results = []
        for name, path, payload, field in cases:
            request = Request(BASE_URL + path, data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urlopen(request, timeout=10) as response:
                    status = response.status
                    body = json.load(response)
            except HTTPError as exc:
                status = exc.code
                body = json.load(exc)
            locations = [row.get("loc", []) for row in body.get("detail", []) if isinstance(row, dict)] if isinstance(body.get("detail"), list) else []
            matched = ["body", field] in locations
            passed = status == 422 and matched
            results.append({"case": name, "path": path, "http_status": status,
                            "target_field": field, "target_validation_error_present": matched,
                            "error_locations": locations, "passed": passed})
            print(f"{'PASS' if passed else 'FAIL'}: {name} | HTTP {status} | field={field}")
        after = {path: sorted(row["id"] for row in get_json(path)) for path in ("/images", "/posts")}
        unchanged = before == after
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "base_url": BASE_URL, "loaded_limits": limits, "cases": results,
                  "record_ids_unchanged": unchanged,
                  "record_counts": {path: len(ids) for path, ids in after.items()},
                  "gemini_requests_sent_by_probe": 0,
                  "passed": unchanged and all(row["passed"] for row in results),
                  "limits": ["Every request deliberately omitted a required field as a safety guard.",
                             "IDs were compared before and after; this is not a database concurrency test."]}
        reports = PROJECT_ROOT / "reports"
        reports.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = reports / f"live_api_validation_{stamp}.json"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except Exception as exc:
        raise SystemExit(f"Live validation check failed: {type(exc).__name__}. Details withheld to protect secrets.") from None
    print("Image and post record IDs unchanged:", unchanged)
    print("Report saved:", output)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

