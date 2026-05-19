# Lemonade Cashier

Lemonade Cashier is a local-first cashier assistant with a deterministic
financial core, append-only audit log, pure replay, and optional offline agent
fallbacks.

The current shipped layers are inventory, cart, totals, cash, receipts, audit,
replay, cash-in-transit, safety, and agents. Camera, speech, and sensor fusion
remain interface-only until the next phase.

Start with the [README on GitHub](https://github.com/bong-water-water-bong/lemonade-cashier#readme),
then use these docs for the project rules and architecture:

- [Architecture](ARCHITECTURE.md)
- [Vision pipeline](VISION_PIPELINE.md)
- [Build order](BUILD_ORDER.md)
- [Safety posture](SAFETY.md)
