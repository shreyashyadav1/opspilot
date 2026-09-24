package dev.opspilot.orders.web;

import dev.opspilot.orders.failure.LatencyInterceptor;
import io.micrometer.observation.ObservationPredicate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.server.observation.ServerRequestObservationContext;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final LatencyInterceptor latencyInterceptor;

    public WebConfig(LatencyInterceptor latencyInterceptor) {
        this.latencyInterceptor = latencyInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(latencyInterceptor).addPathPatterns("/orders", "/orders/**");
    }

    /**
     * Keeps admin and actuator traffic out of request metrics and traces, matching the Python
     * services: control-plane calls must not show up in the telemetry an investigator reads.
     */
    @Bean
    ObservationPredicate excludeOperationalEndpoints() {
        return (name, context) -> {
            if (context instanceof ServerRequestObservationContext serverContext) {
                String uri = serverContext.getCarrier().getRequestURI();
                return !(uri.startsWith("/admin") || uri.startsWith("/actuator"));
            }
            return true;
        };
    }
}
