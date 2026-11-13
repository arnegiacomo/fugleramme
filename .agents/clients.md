# The clients

Covers what core owes the programs that show the page on other devices.

- They live in [fugleramme/clients](https://github.com/fugleramme/clients), a community repo under the fugleramme org. The `@fugleramme/maintainers` team maintains it together, and anyone who brings a working client for new hardware joins it. The people who own a board look after its folder.
- The contract is `/frame.e6`, `/frame.png` and `/press`, as `docs/screens.md` documents them. Nothing else is promised to a client: not `/state`, not `/collage.png`, not any query parameter a client adds.
- A PR that breaks one of the three tags `@fugleramme/maintainers`.
- A bug in a client program, or a PR adding one, belongs in the clients repo: point it there. A bug in the three endpoints stays here.
- `examples/inky` is the one client core keeps, since it runs on the hardware this repo is tested on. Its installer is curl'd from core's `main`.
