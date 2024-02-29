# Starlette Responses Kit
**starlette-responses-kit** is an extension for Starlette, providing a collection of custom responses designed to enhance and simplify the development of web applications and APIs. This toolkit expands on Starlette's built-in responses, offering more flexibility and functionality to handle various content types and response patterns more efficiently.

# Roadmap
- [ ] Custom File Responses: Simplify the process of serving files with enhanced control over content-disposition and content types.
- [ ] JSON File Response: Serve JSON content from files directly, optimizing for speed and memory usage.
- [x] Text and Bytes File Response: Offer explicit responses for text and binary content, providing a clear and concise way to handle different file types.
- [x] Async Support: Fully asynchronous responses, ensuring high performance and non-blocking I/O operations.
- [x] Easy Integration: Designed to seamlessly integrate with existing Starlette applications or FastAPI projects that use Starlette internally.
- [ ] Flexible and Extensible: Easily extend the kit with custom response types to suit your specific needs.

# Installation
Install starlette-responses-kit using pip:


```bash
pip install starlette-responses-kit
```

# Quick Start
Here's how to use one of the custom responses in a Starlette application:

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette_responses_kit import TextFileResponse
from starlette.routing import Route

async def json_file_endpoint(request):
    return TextFileResponse("some-text")

app = Starlette(
    debug=True,
    routes=[
        Route("/text", json_file_endpoint),
    ],
)
```

# Contributing
Contributions are welcome! If you'd like to contribute, please fork the repository and use a feature branch. Pull requests are warmly welcome.

# License
starlette-responses-kit is released under the MIT License. See the bundled LICENSE file for details.
