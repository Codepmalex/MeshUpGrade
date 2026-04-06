import asyncio
import headless

if __name__ == "__main__":
    try:
        asyncio.run(headless.main())
    except KeyboardInterrupt:
        print("\nStopping MeshCoreGrade.")
