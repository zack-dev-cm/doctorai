#!/usr/bin/env python3
"""Generate DoctorAI brand assets using the Gemini image model.

Expects GOOGLE_API_KEY to be available in the environment (e.g., from ~/.bashrc).
Optionally override the model with GENAI_MODEL_ID.
Outputs:
- assets/doctorai-hero.png (hero illustration)
- assets/doctorai-logo.png (horizontal logo for app UI)
- assets/doctorai-mini.png (square mini-app icon)
"""
from pathlib import Path
import os

from google import genai
from google.genai import types


HERO_PROMPT = """
Design a clean hero illustration for DoctorAI: calming telehealth vibe, soft whites,
teal and blue accents, abstract medical UI panels, and a subtle human touch.
Make it minimal, tech-forward, and high-trust. No text, no logos.
""".strip()

LOGO_PROMPT = """
Design a horizontal DoctorAI wordmark with a compact symbol: clean sans lettering,
soft corners, teal + blue gradient accent, healthcare cross hinted in the icon.
Keep background light/transparent feel and avoid clutter.
""".strip()

MINI_PROMPT = """
Design a square mini-app icon for DoctorAI: minimal teal/blue gradient pill with a
simple cross + AI spark motif, rounded corners, high contrast, flat vector look.
No text.
""".strip()


def generate_image(client: genai.Client, model_id: str, prompt: str, out_path: Path, aspect_ratio: str, image_size: str = "1K") -> None:
    """Generate a single image from Gemini and write to disk."""
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
        ),
    )

    candidate = response.candidates[0]
    parts = [
        part.inline_data
        for part in candidate.content.parts
        if getattr(part, "inline_data", None)
    ]
    if not parts:
        raise SystemExit(f"Model did not return an image payload for {out_path.name}.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(parts[0].data)
    print(f"Saved {out_path}")


def main() -> None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY is not set; export it before running.")

    model_id = os.environ.get("GENAI_MODEL_ID", "gemini-3-pro-image-preview")
    client = genai.Client(api_key=api_key)

    generate_image(
        client=client,
        model_id=model_id,
        prompt=HERO_PROMPT,
        out_path=Path("assets/doctorai-hero.png"),
        aspect_ratio="16:9",
    )
    generate_image(
        client=client,
        model_id=model_id,
        prompt=LOGO_PROMPT,
        out_path=Path("assets/doctorai-logo.png"),
        aspect_ratio="16:9",
        image_size="1K",
    )
    generate_image(
        client=client,
        model_id=model_id,
        prompt=MINI_PROMPT,
        out_path=Path("assets/doctorai-mini.png"),
        aspect_ratio="1:1",
        image_size="1K",
    )


if __name__ == "__main__":
    main()
