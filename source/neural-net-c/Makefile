# Build:  mingw32-make          (MSYS2 UCRT64; or plain: make)
# Plain g++ equivalents are given above each target.
CXX      = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -O2 -static
LIB_SRC = src/nn.cpp src/activations.cpp src/loss.cpp

all: xor gradcheck mnist

# g++ -std=c++17 -Wall -Wextra -O2 -static -o xor src/main_xor.cpp src/nn.cpp src/activations.cpp src/loss.cpp
xor: src/main_xor.cpp $(LIB_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $^

# g++ -std=c++17 -Wall -Wextra -O2 -static -o gradcheck src/gradcheck.cpp src/nn.cpp src/activations.cpp src/loss.cpp
gradcheck: src/gradcheck.cpp $(LIB_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $^

# g++ -std=c++17 -Wall -Wextra -O2 -static -o mnist src/main_mnist.cpp src/data_mnist.cpp src/nn.cpp src/activations.cpp src/loss.cpp
mnist: src/main_mnist.cpp src/data_mnist.cpp $(LIB_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $^

# 'clean' works from both cmd/PowerShell (del) and an MSYS2 shell (rm);
# the '-' prefix lets whichever line doesn't apply fail harmlessly.
clean:
	-del /Q xor.exe gradcheck.exe mnist.exe 2>NUL
	-rm -f xor.exe gradcheck.exe mnist.exe

.PHONY: all clean
