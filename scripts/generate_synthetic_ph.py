"""Deterministically generate synthetic Philippine SMS rows for pipeline checks.

Every row is **synthetic** and developer-authored. These rows exercise the
pipeline; they are not evidence of real-world accuracy.

Each family has several phrasings plus slot fills (amounts, brands, links,
times). A family is one ``group``, so group-aware splits keep its rows together.
Training families (``TRAIN_FAMILIES``) and holdout families
(``HOLDOUT_FAMILIES``) are disjoint by construction, and the holdout uses
different brands, phrasings, and link shapes.

Usage:
    python scripts/generate_synthetic_ph.py --train-out data/raw/ph_supplement_5.csv \
        --holdout-out data/raw/ph_holdout.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLUMNS = ["data_kind", "label", "message", "category", "language", "source", "labeling_confidence", "group"]

TRAIN_SLOTS = {
    "bank": ["SampleBank", "BDO", "BPI", "Landbank"],
    "wallet": ["GCash", "Maya"],
    "courier": ["LBC", "J&T Express", "Ninja Van"],
    "shop": ["Shopee", "Lazada"],
    "amount": ["₱1,250", "₱3,499", "₱560", "₱12,000", "₱899"],
    "big": ["₱50,000", "₱120,000", "₱25,000", "₱300,000"],
    "link": ["http://bit.ly/verify-acct", "https://tinyurl.com/claim-now", "http://secure-login.xyz/ph"],
    "phone": ["09171234567", "09281112233", "09995554321"],
    "time": ["3PM", "7:30 PM", "10AM", "tomorrow morning"],
    "name": ["Ana", "Jun", "Rico", "Mae", "Tita Lorna"],
    "place": ["SM North", "Jollibee Cubao", "the office", "simbahan"],
}

HOLDOUT_SLOTS = {
    "bank": ["Metrobank", "UnionBank", "Security Bank", "RCBC", "PNB", "ChinaBank"],
    "wallet": ["ShopeePay", "Coins.ph", "GrabPay"],
    "courier": ["2GO", "Flash Express", "XDE Logistics"],
    "shop": ["TikTok Shop", "Zalora"],
    "amount": ["₱2,150", "₱7,800", "₱430", "₱15,600", "₱1,099"],
    "big": ["₱80,000", "₱450,000", "₱38,500", "₱1,000,000"],
    "link": ["https://ph-acct-review.top/u", "http://rebrand.ly/refund-ph", "https://claims-portal.site/a"],
    "phone": ["09056667788", "09453332211", "09618889900"],
    "time": ["5PM", "9:15 AM", "Friday", "after lunch"],
    "name": ["Carlo", "Bea", "Nonoy", "Ate Joy", "Lolo Ben"],
    "place": ["Robinsons Galleria", "the clinic", "barangay hall", "Ayala Triangle"],
}

# (label, category, language, family, phrasings)
TRAIN_FAMILIES: list[tuple[str, str, str, str, list[str]]] = [
    (
        "spam",
        "bank_phishing",
        "en",
        "tr_bank_locked",
        [
            "{bank}: Your account is temporarily locked. Verify your identity at {link} within 24 hours.",
            "{bank} ALERT: unusual login detected. Confirm your details here {link} to avoid suspension.",
        ],
    ),
    (
        "spam",
        "bank_phishing",
        "taglish",
        "tr_bank_update",
        [
            "{bank}: Kailangan i-update ang account mo ngayon. Click {link} para hindi ma-block.",
            "Hello po, from {bank}. Na-hold ang card mo, paki-verify sa {link} bago {time}.",
        ],
    ),
    (
        "spam",
        "ewallet_phishing",
        "taglish",
        "tr_wallet_reward",
        [
            "{wallet}: May {amount} rewards ka na hindi pa na-claim! Mag-login sa {link} para makuha.",
            "Congrats! Nanalo ang {wallet} number mo ng {big}. I-claim sa {link} ngayong araw lang.",
        ],
    ),
    (
        "spam",
        "parcel_scam",
        "en",
        "tr_parcel_fee",
        [
            "{courier}: Your parcel is on hold due to unpaid customs fee of {amount}. Pay at {link}.",
            "{courier} notice: delivery failed, address incomplete. Update and pay {amount} at {link}.",
        ],
    ),
    (
        "spam",
        "job_scam",
        "taglish",
        "tr_job_like",
        [
            "Hi! Part-time job, like at share lang ng videos, kita {amount} kada araw. Message {phone} sa WhatsApp.",
            "HIRING: online encoder, no experience needed, {big} monthly. Text {phone} para mag-apply.",
        ],
    ),
    (
        "spam",
        "loan_scam",
        "tl",
        "tr_loan_approved",
        [
            "Aprubado na ang loan mo na {big}! Magbayad lang ng processing fee na {amount} sa {wallet} {phone}.",
            "Kailangan mo ng pera? Pautang {big}, walang collateral. I-text ang {phone} ngayon.",
        ],
    ),
    (
        "spam",
        "prize_scam",
        "taglish",
        "tr_raffle",
        [
            "Congratulations! Napili ka sa {shop} anniversary raffle, premyo {big}. Tumawag sa {phone} bago {time}.",
            "{shop}: Ikaw ang lucky winner ng {big}! Para ma-claim, i-send ang buong pangalan sa {phone}.",
        ],
    ),
    (
        "spam",
        "otp_theft",
        "en",
        "tr_otp_request",
        [
            "Hi this is {wallet} support. We sent you a 6-digit code by mistake, please forward it to {phone}.",
            "{bank} agent here. To cancel the unauthorized transfer, reply with the OTP you just received.",
        ],
    ),
    (
        "spam",
        "investment_scam",
        "en",
        "tr_crypto",
        [
            "Earn {big} in 7 days with our guaranteed crypto plan. Minimum {amount}. Join: {link}",
            "Limited slots! Double your money in 48 hours, trusted by 10,000 Filipinos. Register {link}",
        ],
    ),
    (
        "spam",
        "sim_registration_scam",
        "taglish",
        "tr_sim_reg",
        [
            "Ang SIM mo ay made-deactivate ngayong {time}. I-register ulit sa {link} para hindi mawala ang number mo.",
            "SIM REG FINAL NOTICE: kumpletuhin ang registration sa {link} o ma-block ang linya mo.",
        ],
    ),
    (
        "ham",
        "otp",
        "en",
        "tr_otp_legit",
        [
            "Your {wallet} verification code is [CODE]. Never share this code with anyone, including {wallet} staff.",
            "{bank}: [CODE] is your one-time PIN for login. {bank} will never ask for your OTP.",
        ],
    ),
    (
        "ham",
        "bank_alert",
        "en",
        "tr_bank_debit",
        [
            "{bank}: A purchase of {amount} was made on your card ending 1234. Not you? Call the hotline on the back of your card.",
            "{bank}: You received {amount} via InstaPay. Available balance updated.",
        ],
    ),
    (
        "ham",
        "delivery",
        "en",
        "tr_delivery_update",
        [
            "{courier}: Your order from {shop} is out for delivery today. Rider will call before arrival.",
            "{courier}: Package delivered and received. Thank you for using {courier}.",
        ],
    ),
    (
        "ham",
        "personal",
        "taglish",
        "tr_family_meetup",
        [
            "{name}, nasa {place} na ako. Text mo lang ako pag malapit ka na.",
            "Ma, uuwi ako mga {time}. May ipapabili ka ba bago ako umuwi?",
            "Uy {name}, kita tayo sa {place} mga {time}? Libre ko ang merienda.",
        ],
    ),
    (
        "ham",
        "personal",
        "tl",
        "tr_family_chat",
        [
            "Anak, nakapagluto na ako. Kumain ka bago {time} ha.",
            "{name}, salamat sa padala kahapon. Natanggap na namin, ingat ka diyan.",
            "Pakisabi kay {name} na tumawag siya kay Lola mamaya.",
        ],
    ),
    (
        "ham",
        "work",
        "en",
        "tr_work_note",
        [
            "Hi team, the meeting moved to {time}. Please bring the updated sales report.",
            "{name}, can you send me the invoice for {amount} before {time}? Thanks!",
            "Running late, traffic papuntang {place}. Start without me, {name}.",
        ],
    ),
    (
        "ham",
        "appointment",
        "en",
        "tr_clinic_reminder",
        [
            "Reminder: your dental appointment is on {time} at {place}. Reply C to confirm.",
            "Hi {name}, this confirms your checkup schedule at {time}. Please bring your valid ID.",
        ],
    ),
    (
        "ham",
        "school",
        "taglish",
        "tr_school",
        [
            "Good day parents! Walang pasok sa {time} dahil sa bagyo. Stay safe po.",
            "Reminder: PTA meeting sa {time}. Paki-dala ang report card ng anak ninyo.",
        ],
    ),
    (
        "ham",
        "telco_notice",
        "en",
        "tr_telco_balance",
        [
            "Your load balance is {amount}. Thank you for staying with us.",
            "Your bill of {amount} has been posted. Pay on or before the due date via the official app.",
        ],
    ),
    (
        "ham",
        "legit_link",
        "en",
        "tr_gov_advisory",
        [
            "PAGASA advisory: Signal No. 1 raised over your area until {time}. Monitor official updates.",
            "Your passport appointment is confirmed for {time}. Details are in your registered email.",
        ],
    ),
]

HOLDOUT_FAMILIES: list[tuple[str, str, str, str, list[str]]] = [
    (
        "spam",
        "bank_phishing",
        "en",
        "ho_bank_kyc",
        [
            "{bank} Notice: KYC expired. Your online banking will be restricted at {time}. Renew now: {link}",
            "Dear client, {bank} needs to re-validate your mobile number. Proceed at {link} to keep access.",
            "{bank}: We stopped a transaction of {amount}. If not you, cancel immediately at {link}",
        ],
    ),
    (
        "spam",
        "bank_phishing",
        "tl",
        "ho_bank_tl",
        [
            "Paalala mula sa {bank}: may kahina-hinalang transaksyon na {amount}. Kanselahin sa {link}",
            "{bank}: Hindi na magagamit ang card mo simula {time}. I-activate muli sa {link}",
        ],
    ),
    (
        "spam",
        "ewallet_phishing",
        "en",
        "ho_wallet_refund",
        [
            "{wallet}: A refund of {amount} is waiting for you. Claim before {time} via {link}",
            "{wallet} security: your account will be frozen. Re-verify your selfie at {link}",
            "You have a pending {wallet} cashback of {amount}. Confirm receipt here: {link}",
        ],
    ),
    (
        "spam",
        "parcel_scam",
        "taglish",
        "ho_parcel_redelivery",
        [
            "{courier}: Hindi na-deliver ang package mo. Mag-schedule ng redelivery at bayaran ang {amount} sa {link}",
            "May naka-pending kang parcel sa {courier} warehouse. Kailangan bayaran ang storage fee na {amount}: {link}",
        ],
    ),
    (
        "spam",
        "job_scam",
        "en",
        "ho_job_task",
        [
            "Good day! {shop} is hiring order boosters. Earn {amount} per task, paid daily. Chat {phone} on Telegram.",
            "Remote job offer: rate hotels online, {big} per week. Reply YES and add {phone} on WhatsApp.",
            "Hi {name}, your resume was shortlisted. Daily salary {amount}, no interview. Contact HR at {phone}",
        ],
    ),
    (
        "spam",
        "loan_scam",
        "taglish",
        "ho_loan_harass",
        [
            "FINAL DEMAND: overdue ang loan mo. Kung hindi magbabayad ng {amount} ngayong {time}, ipapakalat namin sa contacts mo.",
            "Pre-approved ka sa {big} cash loan! Mag-send lang ng {amount} insurance fee sa {phone}.",
        ],
    ),
    (
        "spam",
        "prize_scam",
        "en",
        "ho_promo_winner",
        [
            "{shop} 10.10 grand draw: your number won {big}! Present this code to agent {phone} to claim.",
            "Congratulations {name}! You were chosen to receive a brand new phone from {shop}. Pay {amount} shipping at {link}",
        ],
    ),
    (
        "spam",
        "government_impersonation",
        "taglish",
        "ho_ayuda",
        [
            "DSWD AYUDA: Kwalipikado ka sa {big} financial assistance. Mag-fill up sa {link} bago {time}.",
            "PhilHealth: May refund ka na {amount}. I-claim gamit ang link na ito: {link}",
            "SSS: Na-approve ang calamity benefit mo na {big}. I-verify ang account sa {link}",
        ],
    ),
    (
        "spam",
        "government_impersonation",
        "en",
        "ho_traffic_fine",
        [
            "LTO: You have an unpaid traffic violation of {amount}. Settle today at {link} to avoid license suspension.",
            "BIR notice: tax penalty of {amount} detected on your TIN. Pay now: {link}",
        ],
    ),
    (
        "spam",
        "otp_theft",
        "taglish",
        "ho_wrong_otp",
        [
            "Hi po, si {name} ito. Na-send ko sa number mo yung code ko by mistake. Pakibalik yung 6 digits?",
            "Ate/Kuya, {wallet} agent po ito. Pakibigay ang OTP para ma-reverse ang maling transfer na {amount}.",
        ],
    ),
    (
        "spam",
        "investment_scam",
        "taglish",
        "ho_paluwagan",
        [
            "Sali na sa online paluwagan! Maglagay ng {amount}, balik {big} after 15 days. Message {phone}",
            "Kumikita na ang mga OFW sa forex signals namin, {big} kada buwan. Join group: {link}",
        ],
    ),
    (
        "spam",
        "romance_scam",
        "en",
        "ho_romance",
        [
            "Hi dear, I am a US soldier on duty. I sent you a gift box but customs needs {amount}. Pay via {wallet} {phone}",
            "Hello {name}, we matched last week. I'm stuck at the airport and need {amount} for my visa, can you help?",
        ],
    ),
    (
        "spam",
        "sim_registration_scam",
        "en",
        "ho_sim_upgrade",
        [
            "Your SIM is due for 5G upgrade. Avoid losing service on {time} by confirming at {link}",
            "NTC: Unregistered SIMs will be cut off at {time}. Re-register now: {link}",
        ],
    ),
    (
        "ham",
        "otp",
        "taglish",
        "ho_otp_legit",
        [
            "[CODE] ang OTP mo sa {wallet}. Valid sa loob ng 5 minuto. Huwag ibigay kahit kanino.",
            "{bank}: Gamitin ang [CODE] para tapusin ang transfer. Hindi kailanman hihingin ng {bank} ang code na ito.",
        ],
    ),
    (
        "ham",
        "bank_alert",
        "en",
        "ho_bank_credit",
        [
            "{bank}: Your salary credit of {big} has been posted to your account.",
            "{bank}: Bills payment of {amount} to Meralco was successful. Ref no. 88213.",
            "{bank}: Your new card was shipped and will arrive in 5-7 banking days.",
        ],
    ),
    (
        "ham",
        "ewallet_receipt",
        "en",
        "ho_wallet_receipt",
        [
            "You have sent {amount} to {name} via {wallet}. Ref. No. 4402918.",
            "{wallet}: You paid {amount} to {place}. Thank you!",
        ],
    ),
    (
        "ham",
        "delivery",
        "taglish",
        "ho_delivery_rider",
        [
            "Hi po, rider ng {courier} ito. Nasa gate na po ako, pakikuha na lang ng order ninyo.",
            "{courier}: Darating ang parcel mo mula {shop} bukas, {time}. Salamat sa paghihintay.",
        ],
    ),
    (
        "ham",
        "personal",
        "en",
        "ho_friends",
        [
            "Happy birthday {name}! Dinner at {place} on {time}, my treat.",
            "Did you get home safe from {place}? Text me when you can.",
            "{name}, I'm bringing pancit to {place} at {time}. Don't be late!",
            "{name}, I left your umbrella at {place}. Pick it up anytime.",
        ],
    ),
    (
        "ham",
        "personal",
        "tl",
        "ho_family_tl",
        [
            "Nak, nagpadala na ako ng {amount} pambayad sa tuition. Tingnan mo mamaya.",
            "{name}, may handaan kina Lola sa Linggo. Sama ka ha.",
            "Pauwi na ako mga {time}, bili ako ng pandesal. Ilan gusto mo?",
            "{name}, nasaan ka na? Andito na kami sa {place}.",
        ],
    ),
    (
        "ham",
        "work",
        "taglish",
        "ho_work_taglish",
        [
            "Guys, extended ang deadline ng report hanggang {time}. Paki-update ang tracker.",
            "{name}, pa-review naman ng slides bago ko i-send kay boss. Salamat!",
        ],
    ),
    (
        "ham",
        "appointment",
        "en",
        "ho_vet_reminder",
        [
            "Paws Clinic: {name}'s vaccine booster is due on {time}. Call us to reschedule.",
            "Your car is ready for pickup at {place}. Service total: {amount}.",
        ],
    ),
    (
        "ham",
        "community",
        "taglish",
        "ho_barangay",
        [
            "Barangay advisory: may water interruption bukas mula 8AM hanggang {time}. Mag-ipon po ng tubig.",
            "Paalala: libreng bakuna sa {place} ngayong Sabado. Dalhin ang health card.",
        ],
    ),
    (
        "ham",
        "legit_link",
        "en",
        "ho_utility",
        [
            "Meralco: Your bill for this month is {amount}, due on the 25th. View it in the official Meralco app.",
            "Manila Water: scheduled maintenance in your area on {time}. We apologize for the inconvenience.",
        ],
    ),
]


def _fill(template: str, slots: dict[str, list[str]], rng: random.Random) -> str:
    out = template
    for key, values in slots.items():
        token = "{" + key + "}"
        while token in out:
            out = out.replace(token, rng.choice(values), 1)
    return out


def generate(
    families: list[tuple[str, str, str, str, list[str]]],
    slots: dict[str, list[str]],
    *,
    per_phrasing: int,
    source: str,
    seed: int,
) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, category, language, family, phrasings in families:
        for phrasing in phrasings:
            attempts = 0
            produced = 0
            while produced < per_phrasing and attempts < per_phrasing * 20:
                attempts += 1
                message = _fill(phrasing, slots, rng)
                key = " ".join(message.casefold().split())
                if key in seen:
                    continue
                seen.add(key)
                produced += 1
                rows.append(
                    {
                        "data_kind": "synthetic",
                        "label": label,
                        "message": message,
                        "category": category,
                        "language": language,
                        "source": source,
                        "labeling_confidence": "high",
                        "group": family,
                    }
                )
    return rows


def write(path: Path, rows: list[dict[str, str]], *, generated_source: str) -> None:
    """Write ``rows`` after the file's existing hand-authored rows.

    Rows previously produced by this generator (same ``source``) are replaced,
    so reruns are idempotent. Existing rows without a group get the same
    derived template key the loader would assign.
    """
    from src.data import make_group_key

    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("source") == generated_source:
                    continue
                kept = {column: (row.get(column) or "") for column in COLUMNS}
                kept["data_kind"] = kept["data_kind"] or "synthetic"
                if not kept["group"]:
                    kept["group"] = make_group_key(kept["message"], category=kept["category"], source=kept["source"])
                existing.append(kept)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows([*existing, *rows])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-out", type=Path, help="Training CSV; existing non-generated rows are kept.")
    parser.add_argument("--holdout-out", type=Path, help="Holdout CSV; existing hand-authored rows are kept.")
    parser.add_argument("--train-per-phrasing", type=int, default=3)
    parser.add_argument("--holdout-per-phrasing", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261021)
    args = parser.parse_args(argv)
    if args.train_out:
        train_rows = generate(
            TRAIN_FAMILIES,
            TRAIN_SLOTS,
            per_phrasing=args.train_per_phrasing,
            source="synthetic_generator_train_v1",
            seed=args.seed,
        )
        write(args.train_out, train_rows, generated_source="synthetic_generator_train_v1")
        print(f"wrote {len(train_rows)} generated training rows to {args.train_out}")
    if args.holdout_out:
        holdout_rows = generate(
            HOLDOUT_FAMILIES,
            HOLDOUT_SLOTS,
            per_phrasing=args.holdout_per_phrasing,
            source="synthetic_holdout_v3",
            seed=args.seed + 1,
        )
        write(args.holdout_out, holdout_rows, generated_source="synthetic_holdout_v3")
        print(f"wrote {len(holdout_rows)} holdout rows to {args.holdout_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
