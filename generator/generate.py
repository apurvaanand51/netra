"""
NETRA synthetic dataset generator.

WHY THIS EXISTS
---------------
The problem statement forbids real seized data, and real data would have no
answer key anyway. So we generate traffic that is *schema-identical* to fused
Bitcoin + network telemetry, and -- crucially -- we PLANT known illicit
typologies and record their hidden labels.

That single design choice is what lets us report real precision/recall/AUC:
    we know the truth, so we can measure whether the models rediscovered it.
Without ground truth, every accuracy claim at a hackathon is a guess.

THE TWO HALVES OF THE DATA
--------------------------
  1. Blockchain layer : txid, input_addresses, output_addresses, amounts
  2. Network layer    : src_ip, dst_ip, ports, geo_country, asn, timestamp

The whole point of NETRA is CORRELATING these two layers. So the generator
emits both, tied together by the transaction.

OUTPUT FILES
------------
  transactions.csv         <- the "seized traffic dump" the analyst uploads
                              (contains ONLY fields a real capture would have)
  ground_truth_entities.csv <- HIDDEN answer key: entity -> label + typology
  ground_truth_addresses.csv<- HIDDEN answer key: address -> owning entity
  README.md                 <- what was planted and how much

The ground-truth files must NEVER be shown to the models at inference time.
They are joined in only inside ml/evaluate.py, to score.

Usage:
    python -m generator.generate                       # defaults
    python -m generator.generate --tx 48000 --out data # demo-size
    python -m generator.generate --tx 500 --out data/smoke   # fast smoke test
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# Country / ASN pool. Realism matters: an investigator's mental model is
# "which country was this wallet controlled from?", so geo has to be plausible.
# --------------------------------------------------------------------------
COUNTRIES: list[tuple[str, str, str]] = [
    ("RU", "AS204601", "Russia"),
    ("NL", "AS9009", "Netherlands"),
    ("DE", "AS51167", "Germany"),
    ("US", "AS13335", "United States"),
    ("SG", "AS14061", "Singapore"),
    ("PA", "AS11556", "Panama"),
    ("IR", "AS58224", "Iran"),
    ("NG", "AS37282", "Nigeria"),
    ("TR", "AS9121", "Turkey"),
    ("HK", "AS45102", "Hong Kong"),
    ("GB", "AS2856", "United Kingdom"),
    ("BR", "AS28573", "Brazil"),
]
CLEAN_COUNTRIES = ["US", "GB", "DE", "NL", "BR", "SG"]  # ordinary users live here
HIGH_RISK_COUNTRIES = ["RU", "PA", "IR", "NG", "TR", "HK"]  # planted-illicit bias

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Typical Bitcoin amount distribution (log-normal) -- most payments are small,
# a few are large. Uniform amounts would make the feature engineering trivial.
AMOUNT_MU = 0.35
AMOUNT_SIGMA = 1.5

# Probability that an ORDINARY (non-laundering) payment also creates a change
# output back to the sender. Set deliberately high, because in real Bitcoin
# almost every payment does. Keeping this realistic is what prevents the model
# from winning on a technicality -- see the comment in Generator._emit.
CLEAN_CHANGE_PROB = 0.55

# Study window: the traffic dump covers this period.
WINDOW_START = datetime(2026, 8, 11, 0, 0, 0)
WINDOW_DAYS = 4


# --------------------------------------------------------------------------
# Entity model
# --------------------------------------------------------------------------
@dataclass
class Entity:
    """One controlling actor -- a wallet cluster or a service."""

    eid: str
    kind: str  # clean | exchange | peel | mixer | ransomware | victim
    addresses: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)
    country: str = "US"
    asn: str = "AS13335"
    label: int = 0  # 1 = illicit (ground truth)
    typology: str = "none"
    countries: list[tuple[str, str]] = field(default_factory=list)  # extra geo hops


@dataclass
class Tx:
    """One transaction observation, carrying BOTH layers."""

    timestamp: datetime
    txid: str
    in_addrs: list[str]
    out_addrs: list[str]
    in_amounts: list[float]
    out_amounts: list[float]
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    geo_country: str
    asn: str
    # --- hidden, never written to transactions.csv ---
    src_entity: str = ""
    dst_entity: str = ""
    typology: str = "background"


class Generator:
    def __init__(self, seed: int, n_clusters: int, n_background: int) -> None:
        self.rng = random.Random(seed)
        self.n_clusters = n_clusters
        self.n_background = n_background
        self.entities: dict[str, Entity] = {}
        self.txs: list[Tx] = []
        self._counter = 0
        # Reused public prefixes make IPs look like a real capture rather than
        # uniformly random noise (which would be an unrealistic giveaway).
        # Each prefix is a full /24, and entities draw addresses within it.
        self._ip_prefixes = [
            f"{self.rng.randint(5, 220)}.{self.rng.randint(0, 255)}.{self.rng.randint(0, 255)}"
            for _ in range(60)
        ]

    # ---------------- primitives ----------------
    def _addr(self) -> str:
        """A plausible bech32-style Bitcoin address."""
        return "bc1q" + "".join(self.rng.choice(B58) for _ in range(38))

    def _ip(self) -> str:
        """A valid dotted-quad IPv4 address inside one of the reused /24s."""
        return f"{self.rng.choice(self._ip_prefixes)}.{self.rng.randint(1, 254)}"

    def _txid(self) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(64))

    def _amount(self, lo: float = 0.001, hi: float = 40.0) -> float:
        """Log-normal draw clipped to a sane range -- realistic payment sizes."""
        value = self.rng.lognormvariate(AMOUNT_MU, AMOUNT_SIGMA)
        return round(min(max(value, lo), hi), 8)

    def _time(self) -> datetime:
        return WINDOW_START + timedelta(
            seconds=self.rng.randint(0, WINDOW_DAYS * 24 * 3600)
        )

    def _new_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    # ---------------- entity factories ----------------
    def _make_clean(self, idx: int) -> Entity:
        """An ordinary user: one country, a few addresses, lots of normal traffic."""
        code, asn, _name = self.rng.choice(
            [(c, a, n) for c, a, n in COUNTRIES if c in CLEAN_COUNTRIES]
        )
        n_addr = self.rng.randint(1, 6)
        ent = Entity(
            eid=self._new_id("E"),
            kind="clean",
            addresses=[self._addr() for _ in range(n_addr)],
            ips=[self._ip() for _ in range(self.rng.randint(1, 3))],
            country=code,
            asn=asn,
            label=0,
            typology="none",
        )
        self.entities[ent.eid] = ent
        return ent

    def _make_exchange(self) -> Entity:
        """A landmark: lawful, but the natural cash-out point. High degree."""
        ent = Entity(
            eid=self._new_id("E"),
            kind="exchange",
            addresses=[self._addr() for _ in range(12)],
            ips=[self._ip() for _ in range(5)],
            country="US",
            asn="AS13335",
            label=0,  # an exchange is not itself illicit
            typology="exchange_service",
        )
        self.entities[ent.eid] = ent
        return ent

    def _make_mixer(self) -> Entity:
        """CoinJoin mixing service: breaks the ownership trail. Illicit."""
        ent = Entity(
            eid=self._new_id("E"),
            kind="mixer",
            addresses=[self._addr() for _ in range(9)],
            ips=[self._ip() for _ in range(4)],
            country="DE",
            asn="AS51167",
            label=1,
            typology="coinjoin_mixer",
        )
        # Cross-border control: the same operator touches several countries.
        ent.countries = [
            ("DE", "AS51167"),
            ("NL", "AS9009"),
            ("PA", "AS11556"),
        ]
        self.entities[ent.eid] = ent
        return ent

    def _make_ransomware(self) -> Entity:
        """A collector wallet: hundreds of victims fan IN, then split out."""
        code, asn, _ = self.rng.choice(
            [(c, a, n) for c, a, n in COUNTRIES if c in HIGH_RISK_COUNTRIES]
        )
        ent = Entity(
            eid=self._new_id("E"),
            kind="ransomware",
            addresses=[self._addr() for _ in range(8)],
            ips=[self._ip() for _ in range(3)],
            country=code,
            asn=asn,
            label=1,
            typology="ransomware_fanin",
        )
        ent.countries = [(code, asn), self.rng.choice(
            [(c, a) for c, a, _ in COUNTRIES if c in HIGH_RISK_COUNTRIES]
        )]
        self.entities[ent.eid] = ent
        return ent

    def _make_victim(self) -> Entity:
        """A ransomware victim: a normal user who pays once."""
        code, asn, _ = self.rng.choice(
            [(c, a, n) for c, a, n in COUNTRIES if c in CLEAN_COUNTRIES]
        )
        ent = Entity(
            eid=self._new_id("E"),
            kind="victim",
            addresses=[self._addr() for _ in range(self.rng.randint(1, 2))],
            ips=[self._ip()],
            country=code,
            asn=asn,
            label=0,  # a victim is not the criminal
            typology="ransomware_victim",
        )
        self.entities[ent.eid] = ent
        return ent

    def _make_peel(self, depth: int) -> list[Entity]:
        """A peel chain: hops that shave off value and forward the remainder."""
        code, asn, _ = self.rng.choice(
            [(c, a, n) for c, a, n in COUNTRIES if c in HIGH_RISK_COUNTRIES]
        )
        chain: list[Entity] = []
        for hop in range(depth):
            ent = Entity(
                eid=self._new_id("E"),
                kind="peel",
                addresses=[self._addr() for _ in range(self.rng.randint(1, 3))],
                ips=[self._ip() for _ in range(self.rng.randint(1, 3))],
                country=code,
                asn=asn,
                label=1,  # every hop in a peel chain is part of the layering
                typology="peel_chain",
            )
            # Later hops drift across borders -- the correlation signal.
            if hop > 0:
                other = self.rng.choice(
                    [(c, a) for c, a, _ in COUNTRIES if c in HIGH_RISK_COUNTRIES]
                )
                ent.countries = [(code, asn), other]
            self.entities[ent.eid] = ent
            chain.append(ent)
        return chain

    def _make_merchant(self) -> Entity:
        """A legitimate high-volume service -- a payment processor or mining pool.

        This entity is a DELIBERATE FALSE-POSITIVE TRAP, and it exists to keep
        the evaluation honest. Statistically it looks like a collector or an
        exchange: enormous volume, hundreds of counterparties, many addresses,
        and IPs spread across several countries because it is a real business
        with real infrastructure.

        But it is lawful. An investigator does not care that a tool can flag
        busy wallets -- they care that it does not waste their week on a payment
        processor. Planting these means our reported precision is measured
        against something that actually tests discrimination, instead of a
        dataset where "busy" and "criminal" happen to coincide.
        """
        base_code, base_asn, _ = self.rng.choice(COUNTRIES)
        ent = Entity(
            eid=self._new_id("E"),
            kind="merchant",
            addresses=[self._addr() for _ in range(self.rng.randint(8, 20))],
            ips=[self._ip() for _ in range(self.rng.randint(4, 8))],
            country=base_code,
            asn=base_asn,
            label=0,  # lawful
            typology="legitimate_service",
        )
        # Real infrastructure spans regions -- so multi-country control alone
        # must NOT be enough to convict a wallet.
        ent.countries = [
            (base_code, base_asn),
            self.rng.choice([(c, a) for c, a, _ in COUNTRIES]),
            self.rng.choice([(c, a) for c, a, _ in COUNTRIES]),
        ]
        self.entities[ent.eid] = ent
        return ent

    def plant_merchant_flow(self, clean: list[Entity], merchants: list[Entity]) -> None:
        """High-volume legitimate traffic through the decoy services."""
        for _ in range(self.n_background // 8):
            self._emit(
                self.rng.choice(clean), self.rng.choice(merchants),
                self._amount(), self._time(), "legitimate_service",
            )
        for _ in range(self.n_background // 8):
            self._emit(
                self.rng.choice(merchants), self.rng.choice(clean),
                self._amount(), self._time(), "legitimate_service",
            )

    # ---------------- transaction emitters ----------------
    def _emit(
        self,
        src: Entity,
        dst: Entity,
        amount: float,
        when: datetime,
        typology: str,
        *,
        split_remainder: bool = False,
        peel_amount: float = 0.0,
    ) -> Tx:
        """Create one transaction from src to dst, with network metadata.

        The network layer is attached here: the sending entity's IP pool
        provides src_ip, the receiving entity's provides dst_ip, and geo comes
        from whichever country that entity was operating from at the time.

        NOTE the deliberate asymmetry that makes correlation necessary:
        a wallet cluster's addresses do not identify its operator, but the IP
        that broadcast its transactions DOES. Only by joining the two layers
        can you say "this wallet was controlled from Iran at 02:11".
        """
        # A real wallet holds several unspent outputs and spends some of them
        # together. Generating that matters enormously: spending multiple
        # addresses in ONE transaction is the observable fact the common-input
        # heuristic keys on. A generator that always emits a single input
        # produces a dataset where entity clustering is impossible -- so the
        # lines below are what make the "Entity Clustering" requirement testable.
        n_inputs = self.rng.randint(1, min(3, len(src.addresses)))
        if n_inputs == 1:
            in_addrs = [self.rng.choice(src.addresses)]
            in_amounts = [round(amount, 8)]
        else:
            in_addrs = self.rng.sample(src.addresses, n_inputs)
            weights = [self.rng.uniform(0.2, 1.0) for _ in range(n_inputs)]
            weight_sum = sum(weights)
            in_amounts = [round(amount * w / weight_sum, 8) for w in weights]

        out_addrs = [self.rng.choice(dst.addresses)]
        out_amounts = [round(amount, 8)]

        if split_remainder:
            # Peel behaviour: a small "peel" to one output, the remainder to
            # another address still owned by the sender (the change output).
            peel = round(peel_amount if peel_amount else amount * self.rng.uniform(0.02, 0.08), 8)
            remainder = round(amount - peel, 8)
            out_addrs = [self.rng.choice(dst.addresses), self.rng.choice(src.addresses)]
            out_amounts = [peel, remainder]
        elif self.rng.random() < CLEAN_CHANGE_PROB:
            # Ordinary wallets create change on most payments too -- this is not
            # a laundering behaviour, it is how Bitcoin works: you spend a whole
            # UTXO and send the difference back to yourself.
            #
            # Modelling this is essential to an HONEST evaluation. If only peel
            # chains produced change outputs, then change_ratio alone would
            # separate the classes perfectly and the model would score AUC 1.000
            # on a technicality rather than on skill. Real change outputs are
            # what force the model to combine several signals.
            payment = round(amount * self.rng.uniform(0.45, 0.92), 8)
            change = round(amount - payment, 8)
            out_addrs = [self.rng.choice(dst.addresses), self.rng.choice(src.addresses)]
            out_amounts = [payment, change]

        # src geo = a country this entity was seen operating from
        if src.countries and self.rng.random() < 0.6:
            src_country, src_asn = self.rng.choice(src.countries)
        else:
            src_country, src_asn = src.country, src.asn
        dst_country, dst_asn = dst.country, dst.asn

        tx = Tx(
            timestamp=when,
            txid=self._txid(),
            in_addrs=in_addrs,
            out_addrs=out_addrs,
            in_amounts=in_amounts,
            out_amounts=out_amounts,
            src_ip=self.rng.choice(src.ips),
            dst_ip=self.rng.choice(dst.ips),
            src_port=self.rng.choice([8333, 8333, 8333, 18333, 443, 9050]),
            dst_port=self.rng.choice([8333, 8333, 8333, 18333, 443, 9050]),
            geo_country=src_country,
            asn=src_asn,
            src_entity=src.eid,
            dst_entity=dst.eid,
            typology=typology,
        )
        self.txs.append(tx)
        return tx

    # ---------------- planting ----------------
    def plant_background(self, clean: list[Entity], illicit: list[Entity] | None = None) -> None:
        """Ordinary peer-to-peer traffic -- the noise the signals hide in.

        Note that a fraction of this traffic also involves the illicit wallets.
        That is deliberate and it is the single most important realism feature
        in the generator: real money launderers also buy coffee. A wallet whose
        ONLY activity is a perfect peel chain is trivially detectable, and a
        model trained on such data would report clean numbers while being
        useless in the field.

        Diluting the planted signature is what makes the reported metrics mean
        something -- and it is why the model has to weigh several features
        together instead of keying on one giveaway.
        """
        pool = clean if not illicit else clean + illicit
        for _ in range(self.n_background):
            # 18% of background traffic touches an illicit wallet, chosen so
            # that "makes normal payments" remains a weak signal rather than
            # an obvious tell in either direction.
            if illicit and self.rng.random() < 0.18:
                other = self.rng.choice(illicit)
                counterparty = self.rng.choice(pool)
                src, dst = (other, counterparty) if self.rng.random() < 0.5 else (counterparty, other)
            else:
                src, dst = self.rng.sample(pool, 2)
            if src is dst:
                continue
            self._emit(src, dst, self._amount(), self._time(), "background")

    def plant_exchange_flow(self, clean: list[Entity], exchanges: list[Entity]) -> None:
        """Many users deposit into an exchange; the exchange pays many out."""
        for _ in range(self.n_background // 12):
            user = self.rng.choice(clean)
            self._emit(user, self.rng.choice(exchanges), self._amount(), self._time(), "exchange_deposit")
        for _ in range(self.n_background // 20):
            self._emit(self.rng.choice(exchanges), self.rng.choice(clean), self._amount(), self._time(), "exchange_withdrawal")

    def plant_peel_chain(self, chain: list[Entity], terminus: Entity, start_value: float, t0: datetime) -> None:
        """Walk the chain, shaving value at each hop."""
        value = start_value
        now = t0
        for i, hop in enumerate(chain):
            nxt = chain[i + 1] if i + 1 < len(chain) else terminus
            self._emit(hop, nxt, value, now, "peel_chain", split_remainder=True)
            now = now + timedelta(minutes=self.rng.randint(3, 40))
            value = round(value * self.rng.uniform(0.94, 0.985), 8)

    def plant_coinjoin(self, mixer: Entity, participants: list[Entity], denom: float, when: datetime) -> None:
        """One CoinJoin round: N inputs of EQUAL value -> N outputs of equal value.

        Mixers are trivially recognisable by a human analyst -- and they are
        also the pattern where the common-input heuristic DELIBERATELY fails,
        which is exactly why we need a separate detector for it.
        """
        ins = [self.rng.choice(p.addresses) for p in participants]
        # Build the coordinated transaction directly (not via _emit) because a
        # CoinJoin has many inputs from many DIFFERENT owners in one tx.
        outs = [self.rng.choice(mixer.addresses) for _ in participants]
        tx = Tx(
            timestamp=when,
            txid=self._txid(),
            in_addrs=ins,
            out_addrs=outs,
            in_amounts=[round(denom, 8) for _ in participants],
            out_amounts=[round(denom, 8) for _ in participants],
            src_ip=self.rng.choice(mixer.ips),
            dst_ip=self.rng.choice(mixer.ips),
            src_port=8333,
            dst_port=8333,
            geo_country=mixer.countries[0][0] if mixer.countries else mixer.country,
            asn=mixer.countries[0][1] if mixer.countries else mixer.asn,
            src_entity=mixer.eid,
            dst_entity=mixer.eid,
            typology="coinjoin_mixer",
        )
        self.txs.append(tx)
        # Then the mixer pays out to the participants' fresh addresses.
        for p in participants:
            self._emit(
                mixer, p, denom, when + timedelta(minutes=self.rng.randint(1, 25)),
                "coinjoin_mixer",
            )

    def plant_ransomware(self, collector: Entity, n_victims: int) -> None:
        """Many victims -> one collector, then the collector splits out."""
        victims = [self._make_victim() for _ in range(n_victims)]
        base = self._time()
        for v in victims:
            self._emit(
                v, collector, self._amount(lo=0.05, hi=2.5),
                base + timedelta(minutes=self.rng.randint(0, 600)), "ransomware_fanin",
            )
        # The collector moves the pot onward in a few large consolidations.
        for _ in range(4):
            target = next((e for e in self.entities.values() if e.kind == "mixer"), None)
            if target is None:
                break
            self._emit(
                collector, target, self._amount(lo=5.0, hi=35.0),
                base + timedelta(hours=self.rng.randint(1, 30)),
                "ransomware_fanin", split_remainder=True,
            )

    # ---------------- top level ----------------
    def build(self) -> None:
        # ------------------------------------------------------------------
        # ORDER MATTERS HERE. We create every entity first, then generate all
        # the traffic. That ordering is what lets us mix illicit wallets into
        # ordinary background traffic (see plant_background), which is the
        # realism feature that keeps the reported metrics meaningful.
        # ------------------------------------------------------------------
        clean = [self._make_clean(i) for i in range(self.n_clusters)]
        exchanges = [self._make_exchange() for _ in range(2)]
        mixers = [self._make_mixer() for _ in range(3)]
        # Decoy services: high-volume but lawful. Planted to test that the
        # models discriminate rather than just flag anything busy.
        merchants = [self._make_merchant() for _ in range(max(6, self.n_clusters // 40))]

        # --- planted typologies: create their entities up front ---
        # The number of planted structures SCALES with the dataset. If it did
        # not, a 50k-transaction dump would still contain only ~30 illicit
        # entities, the positive class would be vanishingly rare, and the risk
        # model would have almost nothing to learn from.
        n_peel = max(6, self.n_background // 2000)
        n_coinjoin = max(5, self.n_background // 2500)
        n_ransomware = max(2, self.n_background // 8000)

        peel_chains = [self._make_peel(depth=self.rng.randint(3, 5)) for _ in range(n_peel)]
        collectors = [self._make_ransomware() for _ in range(n_ransomware)]

        # Everything that should be diluted by normal-looking activity.
        illicit_wallets = [hop for chain in peel_chains for hop in chain] + collectors

        # --- background noise, with illicit wallets diluted into it ---
        self.plant_background(clean, illicit_wallets)
        self.plant_exchange_flow(clean, exchanges)
        self.plant_merchant_flow(clean, merchants)

        # --- now the planted flows, on top of the noise ---
        for chain in peel_chains:
            terminus = self.rng.choice(mixers + exchanges)
            self.plant_peel_chain(
                chain, terminus,
                start_value=self._amount(lo=20.0, hi=90.0),
                t0=self._time(),
            )

        for _ in range(n_coinjoin):
            mixer = self.rng.choice(mixers)
            participants = self.rng.sample(clean, 9)
            self.plant_coinjoin(
                mixer, participants,
                denom=round(self.rng.uniform(0.3, 1.5), 8),
                when=self._time(),
            )

        for collector in collectors:
            self.plant_ransomware(collector, n_victims=self.rng.randint(25, 45))

        self.txs.sort(key=lambda t: t.timestamp)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
TX_HEADER = [
    "timestamp", "txid",
    "src_ip", "dst_ip", "src_port", "dst_port",
    "input_addresses", "output_addresses", "input_amounts", "output_amounts",
    "geo_country", "asn",
]


def write_transactions(gen: Generator, path: Path) -> None:
    """The uploadable artifact. Contains ONLY fields a real capture would have
    -- no labels, no entity ids. That is the whole discipline: if we let the
    answer leak into this file, the metrics would be meaningless."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(TX_HEADER)
        for t in gen.txs:
            writer.writerow([
                t.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                t.txid,
                t.src_ip, t.dst_ip, t.src_port, t.dst_port,
                "|".join(t.in_addrs), "|".join(t.out_addrs),
                "|".join(f"{a:.8f}" for a in t.in_amounts),
                "|".join(f"{a:.8f}" for a in t.out_amounts),
                t.geo_country, t.asn,
            ])


def write_ground_truth(gen: Generator, out_dir: Path) -> None:
    """The answer key. Used ONLY by ml/evaluate.py -- never by the models."""
    with (out_dir / "ground_truth_entities.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["entity_id", "kind", "label", "typology", "country", "asn",
                         "n_addresses", "n_ips"])
        for e in gen.entities.values():
            writer.writerow([e.eid, e.kind, e.label, e.typology, e.country, e.asn,
                             len(e.addresses), len(e.ips)])

    with (out_dir / "ground_truth_addresses.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["address", "entity_id"])
        for e in gen.entities.values():
            for a in e.addresses:
                writer.writerow([a, e.eid])

    with (out_dir / "ground_truth_transactions.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["txid", "src_entity", "dst_entity", "typology"])
        for t in gen.txs:
            writer.writerow([t.txid, t.src_entity, t.dst_entity, t.typology])


def write_readme(gen: Generator, out_dir: Path, n_illicit: int, n_total: int) -> None:
    counts: dict[str, int] = {}
    for e in gen.entities.values():
        counts[e.typology] = counts.get(e.typology, 0) + 1
    tx_counts: dict[str, int] = {}
    for t in gen.txs:
        tx_counts[t.typology] = tx_counts.get(t.typology, 0) + 1

    lines = [
        "# Generated dataset",
        "",
        f"- transactions: **{len(gen.txs):,}**",
        f"- entities: **{n_total:,}**  (illicit: **{n_illicit}**)",
        f"- distinct txids: {len({t.txid for t in gen.txs}):,}",
        "",
        "## Planted entities by typology",
        "",
        "| typology | entities |",
        "|---|---|",
    ]
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {n} |")
    lines += ["", "## Transactions by typology", "", "| typology | transactions |", "|---|---|"]
    for name, n in sorted(tx_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {n:,} |")

    lines += [
        "",
        "## Files",
        "",
        "| file | purpose | visible to the model? |",
        "|---|---|---|",
        "| `transactions.csv` | the uploadable traffic dump | ✅ yes |",
        "| `ground_truth_entities.csv` | entity label + typology | ❌ **no** |",
        "| `ground_truth_addresses.csv` | address → owning entity | ❌ **no** |",
        "| `ground_truth_transactions.csv` | txid → src/dst entity | ❌ **no** |",
        "",
        "> The ground-truth files exist so `ml/evaluate.py` can score the models.",
        "> If any of them is ever read during feature building or inference, the",
        "> metrics become fiction. That is the one rule this design depends on.",
        "",
        "Regenerate with: `python -m generator.generate`",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the NETRA synthetic dataset.")
    parser.add_argument("--out", default="data", help="output directory (default: data)")
    parser.add_argument("--clusters", type=int, default=240, help="number of clean wallet clusters")
    parser.add_argument("--tx", type=int, default=18000, help="number of background transactions")
    parser.add_argument("--seed", type=int, default=42, help="random seed (reproducibility)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    gen = Generator(seed=args.seed, n_clusters=args.clusters, n_background=args.tx)
    gen.build()

    write_transactions(gen, out_dir / "transactions.csv")
    write_ground_truth(gen, out_dir)

    n_total = len(gen.entities)
    n_illicit = sum(e.label for e in gen.entities.values())
    write_readme(gen, out_dir, n_illicit, n_total)

    print(f"Wrote {out_dir}/transactions.csv        ({len(gen.txs):,} transactions)")
    print(f"Wrote {out_dir}/ground_truth_*.csv      (hidden answer key)")
    print(f"  entities : {n_total:,}  of which illicit: {n_illicit}")
    print(f"  illicit rate: {n_illicit / max(n_total, 1):.1%}  (realistic -- positive class is a minority)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
