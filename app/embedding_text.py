from app.schemas import VisionMetadata


def build_image_embedding_text(metadata: VisionMetadata) -> str:
    subject = " ".join(metadata.subject.split())
    category = " ".join(metadata.category.split())
    caption = " ".join(metadata.caption.split())

    if not all((subject, category, caption)):
        raise ValueError("Image description fields must contain text.")

    attributes = sorted({
        " ".join(attribute.split())
        for attribute in metadata.attributes
        if attribute.strip()
    })

    lines = [
        f"Subject: {subject}",
        f"Category: {category}",
    ]
    if attributes:
        lines.append(f"Attributes: {', '.join(attributes)}")
    lines.append(f"Caption: {caption}")

    return "\n".join(lines)
