package main

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strings"
	"syscall"
	"time"
)

func loadSecret(name string) error {
	fileName := name + "_FILE"
	direct, file := os.Getenv(name), os.Getenv(fileName)
	if direct != "" && file != "" {
		return fmt.Errorf("%s and %s cannot both be set", name, fileName)
	}
	if file == "" {
		return nil
	}
	info, err := os.Lstat(file)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() > 65536 {
		return fmt.Errorf("%s is not a valid secret file", fileName)
	}
	raw, err := os.ReadFile(file)
	if err != nil {
		return fmt.Errorf("cannot read %s", fileName)
	}
	value := strings.TrimSpace(string(raw))
	if value == "" || strings.ContainsAny(value, "\x00\r\n") {
		return fmt.Errorf("%s contains an invalid secret", fileName)
	}
	if err := os.Setenv(name, value); err != nil {
		return errors.New("cannot set secret environment")
	}
	return os.Unsetenv(fileName)
}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		connection, err := net.DialTimeout("tcp", "127.0.0.1:9000", 2*time.Second)
		if err != nil {
			os.Exit(1)
		}
		connection.Close()
		return
	}
	for _, name := range []string{"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"} {
		if err := loadSecret(name); err != nil {
			fmt.Fprintln(os.Stderr, "minio entrypoint:", err)
			os.Exit(1)
		}
	}
	args := append([]string{"minio"}, os.Args[1:]...)
	if err := syscall.Exec("/usr/local/bin/minio", args, os.Environ()); err != nil {
		fmt.Fprintln(os.Stderr, "minio entrypoint: cannot start server")
		os.Exit(1)
	}
}
