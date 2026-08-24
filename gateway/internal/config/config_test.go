package config

import (
	"strings"
	"testing"
)

func TestTelemetryConfigDefaults(t *testing.T) {
	t.Setenv("LANCET_GATEWAY__DATABASE_URL", "postgres://user:pass@localhost:5432/db")
	t.Setenv("LANCET_CONFIG_DIR", "../../../config")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() failed: %v", err)
	}

	if cfg.Gateway.Telemetry.OTLPEndpoint != "http://127.0.0.1:4317" {
		t.Errorf("expected default OTLPEndpoint http://127.0.0.1:4317, got %q", cfg.Gateway.Telemetry.OTLPEndpoint)
	}
	if cfg.Gateway.Telemetry.SamplerRatio != 1.0 {
		t.Errorf("expected default SamplerRatio 1.0, got %v", cfg.Gateway.Telemetry.SamplerRatio)
	}
	if cfg.Gateway.Telemetry.ServiceName != "lancet-gateway" {
		t.Errorf("expected default ServiceName lancet-gateway, got %q", cfg.Gateway.Telemetry.ServiceName)
	}
	if cfg.Gateway.Telemetry.DeploymentEnvironment != "dev" {
		t.Errorf("expected default DeploymentEnvironment dev, got %q", cfg.Gateway.Telemetry.DeploymentEnvironment)
	}
}

func TestTelemetryConfigInvalidEndpoint(t *testing.T) {
	t.Setenv("LANCET_GATEWAY__DATABASE_URL", "postgres://user:pass@localhost:5432/db")
	t.Setenv("LANCET_CONFIG_DIR", "../../../config")
	t.Setenv("LANCET_GATEWAY__TELEMETRY__OTLP_ENDPOINT", "not_a_valid_url")

	_, err := Load()
	if err == nil {
		t.Fatal("expected Load() to fail with invalid endpoint, got nil")
	}
	if !strings.Contains(err.Error(), "otlp_endpoint") || !strings.Contains(err.Error(), "not_a_valid_url") {
		t.Errorf("expected error to name key and offending value, got: %v", err)
	}
}

func TestTelemetryConfigInvalidSamplerRatio(t *testing.T) {
	t.Setenv("LANCET_GATEWAY__DATABASE_URL", "postgres://user:pass@localhost:5432/db")
	t.Setenv("LANCET_CONFIG_DIR", "../../../config")

	tests := []struct {
		name  string
		ratio string
	}{
		{"non-numeric", "abc"},
		{"negative", "-0.1"},
		{"above 1", "1.5"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("LANCET_GATEWAY__TELEMETRY__SAMPLER_RATIO", tt.ratio)
			_, err := Load()
			if err == nil {
				t.Fatalf("expected Load() to fail for sampler ratio %q, got nil", tt.ratio)
			}
			if !strings.Contains(err.Error(), "sampler_ratio") {
				t.Errorf("expected error to mention sampler_ratio, got %v", err)
			}
		})
	}
}

func TestTelemetryConfigValidSamplerRatio(t *testing.T) {
	t.Setenv("LANCET_GATEWAY__DATABASE_URL", "postgres://user:pass@localhost:5432/db")
	t.Setenv("LANCET_CONFIG_DIR", "../../../config")

	for _, ratio := range []string{"0.0", "0.5", "1.0"} {
		t.Run(ratio, func(t *testing.T) {
			t.Setenv("LANCET_GATEWAY__TELEMETRY__SAMPLER_RATIO", ratio)
			cfg, err := Load()
			if err != nil {
				t.Fatalf("expected Load() to succeed for ratio %s, got %v", ratio, err)
			}
			var expected float64
			if ratio == "0.0" {
				expected = 0.0
			} else if ratio == "0.5" {
				expected = 0.5
			} else {
				expected = 1.0
			}
			if cfg.Gateway.Telemetry.SamplerRatio != expected {
				t.Errorf("expected %v, got %v", expected, cfg.Gateway.Telemetry.SamplerRatio)
			}
		})
	}
}
