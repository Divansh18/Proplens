import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape public property project data")
    parser.add_argument("--source", choices=("all", "darglobal", "wasalt"), default="all")
    args = parser.parse_args()
    print(f"Scraper for {args.source} will be implemented in step 2.")


if __name__ == "__main__":
    main()
