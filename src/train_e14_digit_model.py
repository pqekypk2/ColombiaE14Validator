from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = ROOT / "reports" / "ocr" / "labeling" / "labels.csv"
DEFAULT_OUT_DIR = ROOT / "reports" / "ocr" / "model"
DEFAULT_MODEL_PATH = DEFAULT_OUT_DIR / "digit_cnn.pt"
IMAGE_SIZE = 32
CELL_COUNT = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_dependencies():
    try:
        import cv2
        import numpy as np
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torch.utils.data import DataLoader, Dataset
    except Exception as exc:
        raise SystemExit(
            "Faltan dependencias para entrenar el modelo. "
            "Instala PyTorch ademas de las dependencias base: python -m pip install torch"
        ) from exc

    class _DigitCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(1, 16, 3, padding=1)
            self.bn1 = nn.BatchNorm2d(16)
            self.conv2 = nn.Conv2d(16, 32, 3, padding=1)
            self.bn2 = nn.BatchNorm2d(32)
            self.conv3 = nn.Conv2d(32, 64, 3, padding=1)
            self.bn3 = nn.BatchNorm2d(64)
            self.dropout = nn.Dropout(0.25)
            self.fc1 = nn.Linear(64 * 4 * 4, 128)
            self.fc2 = nn.Linear(128, 10)

        def forward(self, x):
            x = F.max_pool2d(F.relu(self.bn1(self.conv1(x))), 2)
            x = F.max_pool2d(F.relu(self.bn2(self.conv2(x))), 2)
            x = F.max_pool2d(F.relu(self.bn3(self.conv3(x))), 2)
            x = x.reshape(x.shape[0], -1)
            x = self.dropout(F.relu(self.fc1(x)))
            return self.fc2(x)

    return cv2, np, torch, nn, DataLoader, Dataset, _DigitCNN


def digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def normalize_label_value(value: str | None) -> str | None:
    digits = digits_only(value)
    if not digits or len(digits) > CELL_COUNT:
        return None
    return digits.zfill(CELL_COUNT)


def load_label_rows(labels_path: Path) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    skipped = Counter()

    with labels_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            if raw.get("skipped") == "1":
                skipped["marked_skipped"] += 1
                continue
            value = normalize_label_value(raw.get("value"))
            if value is None:
                skipped["invalid_value"] += 1
                continue
            crop_path = Path(raw.get("crop_path", ""))
            if not crop_path.exists():
                skipped["missing_crop"] += 1
                continue
            rows.append(
                {
                    "document_id": str(raw.get("document_id", "")),
                    "relative_path": raw.get("relative_path", ""),
                    "field_key": raw.get("field_key", ""),
                    "field_label": raw.get("field_label", ""),
                    "field_role": raw.get("field_role", ""),
                    "crop_path": crop_path,
                    "value": value,
                }
            )

    return rows, skipped


def split_cells(gray, cv2, cell_count: int = CELL_COUNT):
    height, width = gray.shape[:2]
    cells = []
    for index in range(cell_count):
        x0 = round(width * index / cell_count)
        x1 = round(width * (index + 1) / cell_count)
        cells.append(gray[:, x0:x1])
    return cells


def preprocess_cell(gray, cv2, np, size: int = IMAGE_SIZE):
    if len(gray.shape) == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape[:2]
    y0 = int(height * 0.08)
    y1 = max(y0 + 1, int(height * 0.92))
    x0 = int(width * 0.08)
    x1 = max(x0 + 1, int(width * 0.92))
    roi = gray[y0:y1, x0:x1]

    dark = roi < 210
    if int(dark.sum()) >= 8:
        ys, xs = np.where(dark)
        top = max(0, int(ys.min()) - 4)
        bottom = min(roi.shape[0], int(ys.max()) + 5)
        left = max(0, int(xs.min()) - 4)
        right = min(roi.shape[1], int(xs.max()) + 5)
        roi = roi[top:bottom, left:right]

    ink = 255 - roi
    ink[ink < 18] = 0

    h, w = ink.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((size, size), dtype="float32")

    scale = min((size - 6) / max(w, 1), (size - 6) / max(h, 1))
    resized_w = max(1, int(round(w * scale)))
    resized_h = max(1, int(round(h * scale)))
    resized = cv2.resize(ink, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((size, size), dtype="uint8")
    top = (size - resized_h) // 2
    left = (size - resized_w) // 2
    canvas[top : top + resized_h, left : left + resized_w] = resized
    return (canvas.astype("float32") / 255.0)


def build_digit_examples(rows: list[dict[str, Any]], cv2, np) -> tuple[list[dict[str, Any]], Counter[str]]:
    examples: list[dict[str, Any]] = []
    skipped = Counter()

    for row in rows:
        gray = cv2.imread(str(row["crop_path"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            skipped["unreadable_crop"] += 1
            continue
        cells = split_cells(gray, cv2)
        for index, (cell, label) in enumerate(zip(cells, row["value"])):
            examples.append(
                {
                    "document_id": row["document_id"],
                    "field_key": row["field_key"],
                    "digit_index": index,
                    "label": int(label),
                    "image": preprocess_cell(cell, cv2, np),
                }
            )

    return examples, skipped


def split_by_document(rows: list[dict[str, Any]], seed: int, val_fraction: float):
    document_ids = sorted({row["document_id"] for row in rows})
    rng = random.Random(seed)
    rng.shuffle(document_ids)
    val_count = max(1, int(round(len(document_ids) * val_fraction)))
    val_docs = set(document_ids[:val_count])
    train_docs = set(document_ids[val_count:])
    return train_docs, val_docs


def make_dataset_class(torch, Dataset, cv2, np):
    class _DigitDataset(Dataset):
        def __init__(self, examples, augment: bool = False, multiplier: int = 1) -> None:
            self.examples = list(examples)
            self.augment = augment
            self.multiplier = max(1, int(multiplier))

        def __len__(self) -> int:
            return len(self.examples) * self.multiplier

        def __getitem__(self, index: int):
            item = self.examples[index % len(self.examples)]
            image = item["image"].copy()
            if self.augment:
                angle = random.uniform(-5.0, 5.0)
                scale = random.uniform(0.92, 1.08)
                tx = random.uniform(-2.5, 2.5)
                ty = random.uniform(-2.5, 2.5)
                center = (IMAGE_SIZE / 2.0, IMAGE_SIZE / 2.0)
                matrix = cv2.getRotationMatrix2D(center, angle, scale)
                matrix[0, 2] += tx
                matrix[1, 2] += ty
                image = cv2.warpAffine(
                    image,
                    matrix,
                    (IMAGE_SIZE, IMAGE_SIZE),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
            tensor = torch.from_numpy(image).float().unsqueeze(0)
            label = torch.tensor(item["label"], dtype=torch.long)
            return tensor, label

    return _DigitDataset


def accuracy_from_logits(logits, labels, torch) -> tuple[int, int]:
    predicted = torch.argmax(logits, dim=1)
    return int((predicted == labels).sum().item()), int(labels.numel())


def evaluate_cells(model, loader, torch, device: str) -> float:
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            batch_correct, batch_total = accuracy_from_logits(logits, labels, torch)
            correct += batch_correct
            total += batch_total
    return correct / total if total else 0.0


def train_model(
    examples: list[dict[str, Any]],
    train_docs: set[str],
    val_docs: set[str],
    args: argparse.Namespace,
    deps,
):
    cv2, np, torch, nn, DataLoader, Dataset, ModelClass = deps
    DatasetClass = make_dataset_class(torch, Dataset, cv2, np)

    train_examples = [item for item in examples if item["document_id"] in train_docs]
    val_examples = [item for item in examples if item["document_id"] in val_docs]
    if not train_examples or not val_examples:
        raise SystemExit("No hay suficientes ejemplos para entrenar y validar.")

    train_dataset = DatasetClass(train_examples, augment=True, multiplier=args.augment_multiplier)
    val_dataset = DatasetClass(val_examples, augment=False)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)

    model = ModelClass().to(args.device)
    counts = Counter(item["label"] for item in train_examples)
    weights = []
    for digit in range(10):
        count = max(1, counts.get(digit, 0))
        weights.append((len(train_examples) / 10.0 / count) ** 0.5)
    weight_tensor = torch.tensor(weights, dtype=torch.float32, device=args.device)
    loss_fn = nn.CrossEntropyLoss(weight=weight_tensor)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)

    best_state = None
    best_cell_accuracy = 0.0
    history: list[dict[str, float]] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        for images, labels in train_loader:
            images = images.to(args.device)
            labels = labels.to(args.device)
            optimizer.zero_grad()
            logits = model(images)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()

            running_loss += float(loss.item()) * int(labels.numel())
            batch_correct, batch_total = accuracy_from_logits(logits, labels, torch)
            correct += batch_correct
            total += batch_total

        train_accuracy = correct / total if total else 0.0
        train_loss = running_loss / total if total else 0.0
        val_accuracy = evaluate_cells(model, val_loader, torch, args.device)
        history.append({"epoch": epoch, "train_loss": train_loss, "train_accuracy": train_accuracy, "val_accuracy": val_accuracy})
        print(
            f"Epoch {epoch:02d}/{args.epochs} "
            f"loss={train_loss:.4f} train_cell={train_accuracy:.3f} val_cell={val_accuracy:.3f}",
            flush=True,
        )

        if val_accuracy >= best_cell_accuracy:
            best_cell_accuracy = val_accuracy
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history, best_cell_accuracy


def predict_field_candidates(
    gray,
    model,
    cv2,
    np,
    torch,
    device: str,
    top_k: int = 3,
    max_candidates: int = 30,
) -> list[dict[str, Any]]:
    model.eval()
    cells = split_cells(gray, cv2)
    tensors = [preprocess_cell(cell, cv2, np) for cell in cells]
    batch = torch.from_numpy(np.stack(tensors)).float().unsqueeze(1).to(device)
    with torch.no_grad():
        probs = torch.softmax(model(batch), dim=1).detach().cpu().numpy()

    per_cell = []
    for row in probs:
        indexes = np.argsort(row)[::-1][:top_k]
        per_cell.append([(int(index), float(row[index])) for index in indexes])

    candidates = []
    for combo in itertools.product(*per_cell):
        digits = "".join(str(digit) for digit, _ in combo)
        probability = 1.0
        confidence_sum = 0.0
        for _, prob in combo:
            probability *= prob
            confidence_sum += prob
        candidates.append(
            {
                "digits": digits,
                "value": int(digits),
                "confidence": confidence_sum / max(1, len(combo)) * 100.0,
                "probability": probability,
            }
        )

    candidates.sort(key=lambda item: (item["probability"], item["confidence"]), reverse=True)
    return candidates[:max_candidates]


def predict_field(gray, model, cv2, np, torch, device: str) -> tuple[str, float]:
    candidates = predict_field_candidates(gray, model, cv2, np, torch, device, top_k=3, max_candidates=1)
    if not candidates:
        return "", 0.0
    best = candidates[0]
    digits = str(best["digits"])
    confidence = float(best["confidence"])
    return digits, confidence


def evaluate_fields(rows: list[dict[str, Any]], val_docs: set[str], model, deps, device: str):
    cv2, np, torch, *_ = deps
    predictions = []
    correct = 0
    total = 0
    by_field: dict[str, Counter[str]] = {}

    for row in rows:
        if row["document_id"] not in val_docs:
            continue
        gray = cv2.imread(str(row["crop_path"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        predicted_digits, confidence = predict_field(gray, model, cv2, np, torch, device)
        expected_digits = row["value"]
        expected_value = int(expected_digits)
        predicted_value = int(predicted_digits)
        ok = expected_value == predicted_value
        total += 1
        correct += int(ok)
        field_counter = by_field.setdefault(row["field_key"], Counter())
        field_counter["total"] += 1
        field_counter["correct"] += int(ok)
        predictions.append(
            {
                "document_id": row["document_id"],
                "field_key": row["field_key"],
                "expected_digits": expected_digits,
                "predicted_digits": predicted_digits,
                "expected_value": expected_value,
                "predicted_value": predicted_value,
                "confidence": f"{confidence:.2f}",
                "ok": "1" if ok else "0",
                "crop_path": str(row["crop_path"]),
            }
        )

    accuracy = correct / total if total else 0.0
    return accuracy, predictions, by_field


def write_predictions(path: Path, predictions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "document_id",
        "field_key",
        "expected_digits",
        "predicted_digits",
        "expected_value",
        "predicted_value",
        "confidence",
        "ok",
        "crop_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(predictions)


def save_model(path: Path, model, metrics: dict[str, Any], deps) -> None:
    _, _, torch, *_ = deps
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_type": "DigitCNN",
            "image_size": IMAGE_SIZE,
            "cell_count": CELL_COUNT,
            "state_dict": model.state_dict(),
            "metrics": metrics,
            "created_at": now_iso(),
        },
        path,
    )


def command_train(args: argparse.Namespace) -> int:
    random.seed(args.seed)
    deps = load_dependencies()
    _, _, torch, *_ = deps
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    if args.device == "auto":
        args.device = "cuda" if torch.cuda.is_available() else "cpu"

    rows, row_skips = load_label_rows(args.labels)
    if not rows:
        raise SystemExit(f"No encontre etiquetas validas en {args.labels}")

    examples, example_skips = build_digit_examples(rows, deps[0], deps[1])
    train_docs, val_docs = split_by_document(rows, args.seed, args.val_fraction)

    print(f"Campos etiquetados usables: {len(rows)}")
    print(f"Ejemplos de digitos: {len(examples)}")
    print(f"Docs train/validacion: {len(train_docs)}/{len(val_docs)}")
    print(f"Dispositivo: {args.device}")
    if row_skips:
        print(f"Etiquetas omitidas: {dict(row_skips)}")
    if example_skips:
        print(f"Recortes omitidos: {dict(example_skips)}")
    print(f"Distribucion digitos: {dict(sorted(Counter(item['label'] for item in examples).items()))}")

    model, history, best_cell_accuracy = train_model(examples, train_docs, val_docs, args, deps)
    field_accuracy, predictions, by_field = evaluate_fields(rows, val_docs, model, deps, args.device)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = args.out_dir / "validation_predictions.csv"
    metrics_path = args.out_dir / "metrics.json"
    write_predictions(predictions_path, predictions)

    metrics = {
        "labels_path": str(args.labels),
        "field_count": len(rows),
        "digit_example_count": len(examples),
        "train_document_count": len(train_docs),
        "validation_document_count": len(val_docs),
        "digit_distribution": dict(sorted(Counter(item["label"] for item in examples).items())),
        "best_validation_cell_accuracy": best_cell_accuracy,
        "validation_field_accuracy": field_accuracy,
        "validation_field_count": len(predictions),
        "by_field": {
            field: {
                "correct": counter["correct"],
                "total": counter["total"],
                "accuracy": counter["correct"] / counter["total"] if counter["total"] else 0.0,
            }
            for field, counter in sorted(by_field.items())
        },
        "history": history,
    }
    with metrics_path.open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2, ensure_ascii=True)

    if not args.no_save:
        save_model(args.model_path, model, metrics, deps)

    print(f"Mejor accuracy por celda: {best_cell_accuracy:.3f}")
    print(f"Accuracy por campo completo: {field_accuracy:.3f}")
    print(f"Predicciones validacion: {predictions_path}")
    print(f"Metricas: {metrics_path}")
    if not args.no_save:
        print(f"Modelo: {args.model_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Entrena un modelo local para leer digitos de recortes E-14.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="CSV generado por label_crops.py")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--augment-multiplier", type=int, default=4)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--no-save", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.labels = args.labels.resolve()
    args.out_dir = args.out_dir.resolve()
    args.model_path = args.model_path.resolve()
    return command_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
