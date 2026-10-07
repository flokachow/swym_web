# Third-party notices

swimform's own code is MIT licensed (see [LICENSE](LICENSE)). It includes or depends on:

## three.js (bundled)

The 3D drill demonstration (`swimform/web/viewer/viewer.js`) is built from
`drill3d/src` together with [three.js](https://threejs.org), which is bundled into
the file. Its licence notice is also kept at the end of `viewer.js`.

```
The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

Rebuild the bundle with `cd drill3d && npm ci && npm run build`. Running swimform
does not need Node.

## Pillow (runtime dependency)

Image drawing for the annotated frames uses [Pillow](https://python-pillow.org),
installed from PyPI (HPND licence). It is not redistributed in this repository.

## ffmpeg (external program)

Video trimming and still extraction call the `ffmpeg` and `ffprobe` programs on
your PATH. They are not part of this repository; install them separately
(see the README) under their own licence.

## Google Gemini API (external service)

Analysis is performed by Google's Gemini API using your own API key, under
[Google's terms](https://ai.google.dev/gemini-api/terms). swimform is not
affiliated with or endorsed by Google.
