import sys
from piano.app import Application


def main() -> None:
    app = Application()
    app.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
