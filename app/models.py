from pydantic import BaseModel
from typing import Literal, Optional

# ---------- Meta lane produces ----------

class MediaBundle(BaseModel):
    reel_id: str                    # ig video id or file hash, used as cache key
    frames_b64: list[str]           # max 8 JPEGs, ~768px wide, base64
    caption: Optional[str] = None   # ig_reel payload "title"
    transcript: Optional[str] = None
    user_hint: Optional[str] = None # text the user sent with/after the reel, e.g. "the jacket"

# ---------- Reap lane produces ----------

class DetectedProduct(BaseModel):
    name: str
    category: str
    brand: Optional[str] = None
    brand_source: Literal["caption", "speech", "visible_logo", "none"]
    attributes: list[str]
    queries: list[str]              # [specific, descriptive, broad]
    best_frame: int
    confidence: float

class ProductCandidate(BaseModel):
    product_id: str
    name: str
    merchant: str
    image_url: Optional[str] = None
    price_min: float
    price_max: float
    currency: str
    default_variant_id: Optional[str] = None

class RecognitionResult(BaseModel):
    detected: DetectedProduct
    match_type: Literal["exact", "similar", "none"]
    query_used: Optional[str] = None
    candidates: list[ProductCandidate]   # top 3

class VariantOption(BaseModel):
    group: str                      # "Size", "Color"
    label: str
    option_id: str
    available: bool

class QuoteSummary(BaseModel):
    quote_id: str
    items_subtotal: float
    shipping: float
    tax: float
    final_amount: float
    currency: str
    expires_at: str
    within_budget: bool
    budget_message: Optional[str] = None

class OrderResult(BaseModel):
    checkout_id: str
    status: str                     # REQUIRES_ACTION, COMPLETED, FAILED...
    approval_url: Optional[str] = None
    order_id: Optional[str] = None
    final_amount: Optional[float] = None
    currency: Optional[str] = None
