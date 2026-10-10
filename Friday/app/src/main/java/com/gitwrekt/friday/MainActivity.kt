package com.gitwrekt.friday

import android.Manifest
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning

// FragmentActivity (not plain ComponentActivity) because BiometricPrompt needs one.
class MainActivity : FragmentActivity() {
    private val vm: AssistantViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { FridayScreen(vm) }
        }
    }

    // Household mode relocks itself if the app sits in the background for a few minutes.
    override fun onStop() { super.onStop(); vm.onBackgrounded() }
    override fun onStart() { super.onStart(); vm.onForegrounded() }
}

private tailrec fun Context.findFragmentActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> baseContext.findFragmentActivity()
    else -> null
}

private val Background = Color(0xFF0E1116)
private val Surface = Color(0xFF1F2630)

@Composable
fun FridayScreen(vm: AssistantViewModel = viewModel()) {
    val context = LocalContext.current
    var hasMic by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val micLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasMic = granted
        if (granted) vm.onMicTapped()
    }

    val activity = remember(context) { context.findFragmentActivity() }

    // Separate scanner for the household-token QR code. Runs in Google's own screen, on-device.
    val tokenScanner = remember {
        GmsBarcodeScanning.getClient(
            context,
            GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
        )
    }
    var showTokenDialog by remember { mutableStateOf(false) }
    var tokenInput by remember { mutableStateOf("") }

    // Fingerprint (PIN fallback) releases the household token. Guest needs nothing.
    fun requestUnlock() {
        if (activity == null) return
        if (!vm.hasHouseholdToken) { showTokenDialog = true; return }
        BiometricGate.authenticate(
            activity,
            title = "Unlock household mode",
            onSuccess = { vm.unlockHousehold() },
            onError = { vm.onUnlockError(it) },
        )
    }

    if (showTokenDialog) {
        AlertDialog(
            onDismissRequest = { showTokenDialog = false; tokenInput = "" },
            title = { Text("Household token") },
            text = {
                Column {
                    Text("This is the long FRIDAY_TOKEN from the hub, not your phone PIN. Scan its QR code or paste it. It is stored encrypted, and you unlock it with your fingerprint or PIN.")
                    TextButton(onClick = {
                        tokenScanner.startScan()
                            .addOnSuccessListener { code -> tokenInput = code.rawValue.orEmpty().trim() }
                            .addOnFailureListener { e -> vm.onScanError(e.message) }
                    }) { Text("Scan QR from hub") }
                    OutlinedTextField(
                        value = tokenInput,
                        onValueChange = { tokenInput = it },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val saved = vm.saveHouseholdToken(tokenInput)
                    tokenInput = ""
                    showTokenDialog = false
                    if (saved) requestUnlock()
                }) { Text("Save and unlock") }
            },
            dismissButton = {
                TextButton(onClick = { showTokenDialog = false; tokenInput = "" }) { Text("Cancel") }
            },
        )
    }

    // Google's code scanner runs in its own screen, so Friday needs no camera permission.
    // Product barcodes only (UPC and EAN), which keeps scans fast and ignores QR codes.
    val scanner = remember {
        GmsBarcodeScanning.getClient(
            context,
            GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(
                    Barcode.FORMAT_EAN_13,
                    Barcode.FORMAT_EAN_8,
                    Barcode.FORMAT_UPC_A,
                    Barcode.FORMAT_UPC_E,
                )
                .build()
        )
    }

    val accent = Color(0xFFFF8A80)
    val listState = rememberLazyListState()
    LaunchedEffect(vm.messages.size) {
        if (vm.messages.isNotEmpty()) listState.animateScrollToItem(vm.messages.lastIndex)
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(Background)
            .safeDrawingPadding()
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text(Persona.displayName, color = accent, fontSize = 22.sp)
                val tierLabel = if (vm.tier == Tier.HOUSEHOLD) "household" else "guest"
                Text(
                    tierLabel + if (vm.offline) " · offline mode" else "",
                    color = Color.Gray,
                    fontSize = 12.sp,
                )
            }
            Spacer(Modifier.weight(1f))
            if (vm.tier == Tier.HOUSEHOLD) {
                // Pantry adds are household-only, so Scan only exists while unlocked.
                TextButton(
                    enabled = vm.status != Status.THINKING,
                    onClick = {
                        scanner.startScan()
                            .addOnSuccessListener { barcode -> vm.onBarcodeScanned(barcode.rawValue) }
                            .addOnFailureListener { e -> vm.onScanError(e.message) }
                    },
                ) { Text("Scan") }
                TextButton(onClick = vm::lockHousehold) { Text("Lock") }
            } else {
                TextButton(onClick = { requestUnlock() }) { Text("Unlock") }
            }
            TextButton(onClick = vm::clearHistory) { Text("Clear") }
        }

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            items(vm.messages) { m -> Bubble(m, accent) }
        }

        if (vm.partial.isNotBlank()) {
            Text(
                "“${vm.partial}”",
                color = Color.LightGray,
                fontStyle = FontStyle.Italic,
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }
        vm.error?.let {
            Text(it, color = Color(0xFFFF6E6E), modifier = Modifier.padding(bottom = 8.dp))
        }

        val name = Persona.displayName
        val label = when (vm.status) {
            Status.IDLE -> "Talk to $name"
            Status.LISTENING -> "Listening…  (tap to cancel)"
            Status.THINKING -> "Thinking…  (tap to cancel)"
            Status.SPEAKING -> "Speaking…  (tap to interrupt)"
        }
        Button(
            onClick = {
                if (hasMic) vm.onMicTapped() else micLauncher.launch(Manifest.permission.RECORD_AUDIO)
            },
            colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = Color.Black),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth().height(72.dp),
        ) { Text(label, fontSize = 18.sp) }

        TextButton(onClick = vm::cycleVoice, modifier = Modifier.fillMaxWidth()) {
            Text(
                "Voice: ${vm.voiceLabel}  ▸",
                color = Color.Gray,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun Bubble(m: ChatMessage, accent: Color) {
    val mine = m.role == "user"
    Box(
        Modifier.fillMaxWidth(),
        contentAlignment = if (mine) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Text(
            m.text,
            color = if (mine) Color.Black else Color.White,
            modifier = Modifier
                .widthIn(max = 300.dp)
                .background(if (mine) accent else Surface, RoundedCornerShape(14.dp))
                .padding(12.dp),
        )
    }
}
