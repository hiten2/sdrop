# sdrop - a small temporary file storage server
## protocol
### overarching protocol
a POST stores the transmitted file, and a GET simultaneously gets, shreds, and unlinks the requested file
### file transfer protocol
sdrop operates over HTTP, and follows a simple protocol consisting of 2 components:
1. Content-Length header - a variable-length integer representing the file length
2. HTTP body - the actual file
