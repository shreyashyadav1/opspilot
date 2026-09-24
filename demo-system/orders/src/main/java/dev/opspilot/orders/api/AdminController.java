package dev.opspilot.orders.api;

import dev.opspilot.orders.export.OrderExportJob;
import dev.opspilot.orders.failure.FailureModes;
import dev.opspilot.orders.failure.FailureState;
import dev.opspilot.orders.runtime.RuntimeSettings;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Internal admin API used by the control plane (deploys and failure modes). Kept out of logs,
 * metrics and traces; see WebConfig and AccessLogFilter.
 */
@RestController
@RequestMapping("/admin")
public class AdminController {

    public record ConfigUpdate(String version, Map<String, Object> values) {}

    private final FailureState failures;
    private final OrderExportJob exportJob;
    private final RuntimeSettings settings;

    public AdminController(FailureState failures, OrderExportJob exportJob, RuntimeSettings settings) {
        this.failures = failures;
        this.exportJob = exportJob;
        this.settings = settings;
    }

    @GetMapping("/failures")
    public FailureModes getFailures() {
        return failures.modes();
    }

    @PutMapping("/failures")
    public FailureModes setFailures(@Valid @RequestBody FailureModes modes) {
        failures.set(modes);
        if (modes.poolExhaustion()) {
            exportJob.startLeaking();
        } else {
            exportJob.stop();
        }
        return modes;
    }

    @DeleteMapping("/failures")
    public FailureModes clearFailures() {
        failures.set(FailureModes.NONE);
        exportJob.stop();
        return FailureModes.NONE;
    }

    @GetMapping("/config")
    public Map<String, Object> getConfig() {
        return Map.of("version", settings.version(), "values", settings.snapshot());
    }

    @PutMapping("/config")
    public Map<String, Object> putConfig(@RequestBody ConfigUpdate update) {
        try {
            settings.apply(update.version(), update.values() == null ? Map.of() : update.values());
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, e.getMessage());
        }
        return getConfig();
    }
}
