// OsosFs on a PC directory, for tests.
#pragma once
#include <filesystem>
#include <fstream>
#include <string>
#include "profile_store.h"

class HostFs : public OsosFs {
 public:
  explicit HostFs(const std::string& root) : root_(root) {
    std::filesystem::remove_all(root_);
    std::filesystem::create_directories(root_ + OSOS_PF_DIR);
  }
  size_t free_bytes = 1 << 20;
  bool fail_writes = false;

  int size(const char* path) override {
    std::error_code ec;
    auto n = std::filesystem::file_size(full(path), ec);
    return ec ? -1 : (int)n;
  }
  bool write(const char* path, const void* data, size_t n, bool append) override {
    if (fail_writes) return false;
    std::ofstream f(full(path), std::ios::binary | (append ? std::ios::app : std::ios::trunc));
    f.write((const char*)data, (std::streamsize)n);
    return (bool)f;
  }
  int read(const char* path, size_t off, void* data, size_t n) override {
    std::ifstream f(full(path), std::ios::binary);
    if (!f) return -1;
    f.seekg((std::streamoff)off);
    f.read((char*)data, (std::streamsize)n);
    return (int)f.gcount();
  }
  bool remove(const char* path) override {
    std::error_code ec;
    return std::filesystem::remove(full(path), ec);
  }
  bool rename(const char* from, const char* to) override {
    std::error_code ec;
    std::filesystem::rename(full(from), full(to), ec);
    return !ec;
  }
  size_t freeBytes() override { return free_bytes; }
  void list(const char* dir, void (*cb)(const char*, void*), void* ctx) override {
    for (auto& e : std::filesystem::directory_iterator(full(dir)))
      if (e.is_regular_file()) cb(e.path().filename().string().c_str(), ctx);
  }
  std::string full(const char* p) const { return root_ + p; }

 private:
  std::string root_;
};
