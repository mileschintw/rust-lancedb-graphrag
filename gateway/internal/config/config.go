// Package config owns the gateway's TOML-plus-environment configuration contract.
package config

import (
	"errors"
	"fmt"
	"math"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/spf13/viper"
)

// TelemetryConfig holds the gateway's OpenTelemetry configuration (D-32, D-34, D-43, D-84).
type TelemetryConfig struct {
	OTLPEndpoint          string  `mapstructure:"otlp_endpoint"`
	SamplerRatio          float64 `mapstructure:"sampler_ratio"`
	ServiceName           string  `mapstructure:"service_name"`
	DeploymentEnvironment string  `mapstructure:"deployment_environment"`
}

// Config holds the gateway service configuration.
type Config struct {
	Gateway struct {
		Port        string          `mapstructure:"port"`
		DatabaseURL string          `mapstructure:"database_url"`
		EngineAddr  string          `mapstructure:"engine_addr"`
		Telemetry   TelemetryConfig `mapstructure:"telemetry"`
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

	v.SetDefault("gateway.telemetry.otlp_endpoint", "http://127.0.0.1:4317")
	v.SetDefault("gateway.telemetry.sampler_ratio", 1.0)
	v.SetDefault("gateway.telemetry.service_name", "lancet-gateway")
	v.SetDefault("gateway.telemetry.deployment_environment", "dev")

	_ = v.BindEnv("gateway.port", "LANCET_GATEWAY__PORT")
	_ = v.BindEnv("gateway.database_url", "LANCET_GATEWAY__DATABASE_URL")
	_ = v.BindEnv("gateway.engine_addr", "LANCET_GATEWAY__ENGINE_ADDR")
	_ = v.BindEnv("gateway.telemetry.otlp_endpoint", "LANCET_GATEWAY__TELEMETRY__OTLP_ENDPOINT")
	_ = v.BindEnv("gateway.telemetry.sampler_ratio", "LANCET_GATEWAY__TELEMETRY__SAMPLER_RATIO")
	_ = v.BindEnv("gateway.telemetry.service_name", "LANCET_GATEWAY__TELEMETRY__SERVICE_NAME")
	_ = v.BindEnv("gateway.telemetry.deployment_environment", "LANCET_GATEWAY__TELEMETRY__DEPLOYMENT_ENVIRONMENT")

	if err := v.ReadInConfig(); err != nil {
		return Config{}, err
	}
	if environment := os.Getenv("LANCET_ENV"); environment != "" {
		v.SetConfigName("config." + environment)
		if err := v.MergeInConfig(); err != nil {
			return Config{}, err
		}
	}

	// Check raw env override for non-numeric sampler ratio before viper unmarshal
	if rawEnv := os.Getenv("LANCET_GATEWAY__TELEMETRY__SAMPLER_RATIO"); strings.TrimSpace(rawEnv) != "" {
		if _, err := strconv.ParseFloat(strings.TrimSpace(rawEnv), 64); err != nil {
			return Config{}, fmt.Errorf("gateway.telemetry.sampler_ratio must be a float in range 0.0..=1.0, got %q", rawEnv)
		}
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return Config{}, err
	}
	if strings.TrimSpace(cfg.Gateway.DatabaseURL) == "" {
		return Config{}, errors.New("gateway.database_url must not be empty (set LANCET_GATEWAY__DATABASE_URL)")
	}
	if os.Getenv("LANCET_ENV") == "prod" && strings.Contains(cfg.Gateway.DatabaseURL, "sslmode=disable") {
		return Config{}, errors.New("gateway.database_url must not disable TLS in prod")
	}

	// Fail-closed validation for telemetry (D-84)
	if math.IsNaN(cfg.Gateway.Telemetry.SamplerRatio) || cfg.Gateway.Telemetry.SamplerRatio < 0.0 || cfg.Gateway.Telemetry.SamplerRatio > 1.0 {
		return Config{}, fmt.Errorf("gateway.telemetry.sampler_ratio must be a float in range 0.0..=1.0, got %v", cfg.Gateway.Telemetry.SamplerRatio)
	}

	trimmedEndpoint := strings.TrimSpace(cfg.Gateway.Telemetry.OTLPEndpoint)
	if trimmedEndpoint != "" {
		u, err := url.Parse(trimmedEndpoint)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return Config{}, fmt.Errorf("gateway.telemetry.otlp_endpoint must be an absolute http or https URL, got %q", trimmedEndpoint)
		}
	}

	return cfg, nil
}
