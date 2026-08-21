// Package config owns the gateway's TOML-plus-environment configuration contract.
package config

import (
	"errors"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/viper"
)

// Config holds the gateway service configuration.
type Config struct {
	Gateway struct {
		Port        string `mapstructure:"port"`
		DatabaseURL string `mapstructure:"database_url"`
		EngineAddr  string `mapstructure:"engine_addr"`
	} `mapstructure:"gateway"`
}

// Load reads configuration from TOML files and environment variables.
func Load() (Config, error) {
	v := viper.New()
	dir := os.Getenv("LANCET_CONFIG_DIR")
	if dir == "" {
		for _, candidate := range []string{"../config", "./config"} {
			if _, err := os.Stat(filepath.Join(candidate, "config.toml")); err == nil {
				dir = candidate
				break
			}
		}
	}
	v.SetConfigName("config")
	v.SetConfigType("toml")
	v.AddConfigPath(dir)
	v.SetEnvPrefix("LANCET")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "__"))
	v.AutomaticEnv()
	_ = v.BindEnv("gateway.port", "LANCET_GATEWAY__PORT")
	_ = v.BindEnv("gateway.database_url", "LANCET_GATEWAY__DATABASE_URL")
	_ = v.BindEnv("gateway.engine_addr", "LANCET_GATEWAY__ENGINE_ADDR")
	if err := v.ReadInConfig(); err != nil {
		return Config{}, err
	}
	if environment := os.Getenv("LANCET_ENV"); environment != "" {
		v.SetConfigName("config." + environment)
		if err := v.MergeInConfig(); err != nil {
			return Config{}, err
		}
	}
	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return Config{}, err
	}
	if strings.TrimSpace(cfg.Gateway.DatabaseURL) == "" {
		return Config{}, errors.New("gateway.database_url must not be empty")
	}
	if os.Getenv("LANCET_ENV") == "prod" && strings.Contains(cfg.Gateway.DatabaseURL, "sslmode=disable") {
		return Config{}, errors.New("gateway.database_url must not disable TLS in prod")
	}
	return cfg, nil
}
